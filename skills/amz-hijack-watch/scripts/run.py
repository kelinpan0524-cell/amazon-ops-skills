#!/usr/bin/env python3
"""跟卖监控：盯我们自己 ASIN 的卖家数变化，发现有人跟卖/压价。

用法：
  python3 skills/amz-hijack-watch/scripts/run.py              # 用已存快照重算
  python3 skills/amz-hijack-watch/scripts/run.py --fetch      # 卖家精灵拉最新快照（花额度）
  python3 skills/amz-hijack-watch/scripts/run.py --asins B0XXXXXXXX,B0YYYYYYYY --fetch
  python3 skills/amz-hijack-watch/scripts/run.py --format text

数据：config/watchlist.json 的 our_asins（人工维护）；快照落 data/raw/hijack/ 不进 git。
退出码：有 critical（真的被跟卖/压价）→ 1；否则 0。数据缺失 → 2。

口径：sellers 是 Keepa 统计的该 ASIN 在售 offer 数，含 FBA/FBM。
buyBoxSellerIdHistory 我们的数据源拿不到，所以"购物车易主"只能间接推断，别当成确定结论。
"""
import argparse
import datetime as dt
import json
import os
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent.parent / "_shared"))
import chartlets as c     # noqa: E402
import html_report as hr  # noqa: E402
import mcp_client as mc   # noqa: E402
import metrics as m       # noqa: E402

ROOT = HERE.parent.parent.parent
WATCH_JSON = ROOT / "config" / "watchlist.json"
RAW_DIR = ROOT / "data" / "raw" / "hijack"
OUT_DIR = ROOT / "data" / "reports" / "hijack"
MARKETPLACE = "US"
LOOKBACK_DAYS = 14

# 阈值。价格这几档参照了开源社区的做法（changedetection.io 的 price 插件、
# nexscope 的 amazon-price-tracker）：5% 是行业默认触发线，10% 是"要动手"线，
# 50% 以上基本是抓取读错（不是真降价），要当数据异常而不是价格信号。
PRICE_DROP_ALERT = 0.05      # 跌 >5%：关注
PRICE_DROP_CRITICAL = 0.10   # 跌 >10%：关键品要动手
PRICE_RISE_ALERT = 0.10      # 涨 >10%：可能影响转化，要看销量有没有掉
PRICE_SANITY = 0.50          # 涨跌超 50% 视为数据错误，不报（否则一改版就误报）
SELLER_NEW = 2               # 卖家数达到 2 家 = 有人跟卖
FETCH_FAIL_ALERT = 0.25      # 一轮里超过 25% 拿不到数据 = 抓取坏了，要修


def parse_asins(text):
    """从 hijack-watch.md 抽 ASIN。只认 B0 开头 10 位。"""
    out, seen = [], set()
    for line in text.splitlines():
        for asin in re.findall(r"\bB0[A-Z0-9]{8}\b", line):
            if asin in seen:
                continue
            seen.add(asin)
            note = re.sub(r"\bB0[A-Z0-9]{8}\b", "", line).strip(" |-\t")[:50]
            out.append({"asin": asin, "note": note})
    return out


def load_watchlist():
    """读 config/watchlist.json 的 our_asins；文件不在返回空（由调用方报 needs_data）。"""
    p = ROOT / "config" / "watchlist.json"
    if not p.exists():
        return []
    try:
        d = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    out, seen = [], set()
    for item in d.get("our_asins") or []:
        asin = (item.get("asin") if isinstance(item, dict) else str(item) or "").strip().upper()
        if re.fullmatch(r"B0[A-Z0-9]{8}", asin) and asin not in seen:
            seen.add(asin)
            out.append({"asin": asin, "note": (item.get("note") or "").strip()[:50]})
    return out


def snapshot_path(day=None):
    return RAW_DIR / ("%s.json" % (day or dt.date.today().isoformat()))


def load_all_snapshots():
    """返回 [{"date","items":{asin:{sellers,price}}}]，按日期升序。"""
    snaps = []
    if not RAW_DIR.exists():
        return snaps
    for f in sorted(RAW_DIR.glob("*.json")):
        try:
            d = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if d.get("items"):
            snaps.append(d)
    return snaps


def _series_from(res):
    """卖家精灵返回两种形态：结构化 {ts, series} 或 {_raw: 文本}。统一成 dict。"""
    if not isinstance(res, dict):
        return {}
    if "_raw" in res:
        return {}
    series = res.get("series") or {}
    ts = res.get("ts") or []
    out = {}
    for key, vals in series.items():
        pairs = [(ts[i], v) for i, v in enumerate(vals or [])
                 if i < len(ts) and v is not None]
        if pairs:
            out[key] = pairs
    return out


def fetch_one(client, asin):
    """拉单个 ASIN 的 sellers/price。失败返回 None（不中断整轮）。"""
    for attempt in range(2):
        try:
            res = client.call_tool("keepa.trend", {
                "marketplace": MARKETPLACE, "asin": asin,
                "metrics": ["sellers", "price"],
                "dateRange": {
                    "startDate": (dt.date.today() - dt.timedelta(days=LOOKBACK_DAYS)).isoformat(),
                    "endDate": dt.date.today().isoformat()}})
            s = _series_from(res)
            if not s:
                return None
            sellers = [v for _, v in s.get("sellers", [])]
            prices = [v for _, v in s.get("price", [])]
            return {
                "sellers": int(max(sellers)) if sellers else None,
                "sellers_last": int(sellers[-1]) if sellers else None,
                "price": round(prices[-1], 2) if prices else None,
                "price_min": round(min(prices), 2) if prices else None,
            }
        except (mc.MCPError, OSError, TimeoutError) as e:
            if attempt == 0:
                import time
                time.sleep(2)
                continue
            print("  ! %s 拉取失败：%s" % (asin, str(e)[:80]))
            return None
    return None


def _save_partial(items, failed):
    """每拉完一个 ASIN 就落盘（同 review 的理由：20 个 ASIN 要跑一分多钟，
    中途挂住不该让整轮白跑）。"""
    snap = {"date": dt.date.today().isoformat(), "marketplace": MARKETPLACE,
            "items": items, "failed": failed}
    if items:
        RAW_DIR.mkdir(parents=True, exist_ok=True)
        snapshot_path().write_text(json.dumps(snap, ensure_ascii=False, indent=2),
                                   encoding="utf-8")
    return snap


def fetch_snapshots(asins):
    client = mc.sellersprite_client()
    items, failed = {}, []
    for a in asins:
        d = fetch_one(client, a)
        if d:
            items[a] = d
            print("  · %s 卖家 %s 家，售价 %s" % (a, d.get("sellers_last"), d.get("price")))
        else:
            failed.append(a)
        _save_partial(items, failed)
        import time
        time.sleep(1.0)   # 卖家精灵按次计费，稳一点别触发限流
    return _save_partial(items, failed)


def diff(prev, cur):
    """比对两次快照，返回变化列表（按严重度排序）。"""
    changes = []
    p_items = (prev or {}).get("items") or {}
    c_items = (cur or {}).get("items") or {}
    for asin, c in c_items.items():
        p = p_items.get(asin)
        if not p:
            continue
        ps, cs = p.get("sellers_last"), c.get("sellers_last")
        pp, cp = p.get("price"), c.get("price")

        if ps is not None and cs is not None:
            if ps == 1 and cs >= SELLER_NEW:
                changes.append({"asin": asin, "kind": "出现跟卖", "level": "critical",
                                "msg": "卖家数 %d → %d，有人进来了" % (ps, cs),
                                "action": "去后台看是不是 FBA 跟卖；确认对方价格与配送方式，"
                                          "必要时用品牌备案投诉（人工操作，不自动举报）"})
            elif cs > ps:
                changes.append({"asin": asin, "kind": "跟卖扩散", "level": "high",
                                "msg": "卖家数 %d → %d" % (ps, cs),
                                "action": "看新增卖家价格；若低于我们成本价，先算要不要跟价"})
            elif ps > 1 and cs == 1:
                changes.append({"asin": asin, "kind": "跟卖退出", "level": "info",
                                "msg": "卖家数 %d → 1，购物车回到我们手里" % ps,
                                "action": "无需动作；记一笔方便复盘谁在反复进出"})

        if pp and cp and pp > 0:
            chg = (cp - pp) / pp          # 正=涨，负=跌
            # 超出合理范围的变化当数据错误：抓取读错、单位错、读到了别的变体价，
            # 报出来只会让人去查一个不存在的问题
            if abs(chg) > PRICE_SANITY:
                changes.append({
                    "asin": asin, "kind": "数据异常", "level": "medium",
                    "msg": "售价 $%.2f → $%.2f（%+.0f%%）幅度异常，大概率是抓取读错"
                           % (pp, cp, chg * 100),
                    "action": "先去前台核对真实价格；确认是抓取问题就记一笔，别当价格信号"})
            elif chg <= -PRICE_DROP_ALERT:
                has_rival = (cs or 1) > 1
                severe = abs(chg) >= PRICE_DROP_CRITICAL
                # 分级：有跟卖才是 critical（真被抢购物车）；
                # 没跟卖但跌过 10% 给 high（可能是自己促销，也可能有人在跟价，
                # 值得当天看一眼但不至于半夜叫人）；其余 medium。
                lv = "critical" if has_rival else ("high" if severe else "medium")
                changes.append({
                    "asin": asin, "kind": "价格下跌", "level": lv,
                    "msg": "售价 $%.2f → $%.2f（%+.0f%%）%s"
                           % (pp, cp, chg * 100,
                              "，且有 %d 家卖家 → 像在压价抢购物车" % cs if has_rival
                              else ("，跌幅超过 %.0f%%" % (PRICE_DROP_CRITICAL * 100) if severe else "")),
                    "action": ("先确认不是我们自己调的促销；是对方压价就跟到略低于他，"
                               "别一路往下砸" if has_rival
                               else "确认下是不是我们自己在做活动；不是就查有没有人在跟价")})
            elif chg >= PRICE_RISE_ALERT:
                changes.append({
                    "asin": asin, "kind": "价格上涨", "level": "high",
                    "msg": "售价 $%.2f → $%.2f（%+.0f%%）" % (pp, cp, chg * 100),
                    "action": "涨价通常掉转化：对比这几天的 sessions 和转化率，"
                              "如果单量跟着掉，考虑退回原价或加优惠券"})
    # 抓取健康：一轮里太多 ASIN 拿不到价格，说明数据源出问题了，
    # 这时"没报变化"是假的——不能让人以为一切正常
    total = len(c_items) + len((cur or {}).get("failed") or [])
    n_fail = len((cur or {}).get("failed") or [])
    if total and n_fail / total >= FETCH_FAIL_ALERT:
        changes.insert(0, {
            "asin": "-", "kind": "抓取异常", "level": "high",
            "msg": "%d/%d 个 ASIN 没拉到价格（%.0f%%），这次的变化清单不完整"
                   % (n_fail, total, n_fail / total * 100),
            "action": "检查卖家精灵额度/接口；在修好之前，别把「没有告警」当成「没问题」"})

    order = {"critical": 0, "high": 1, "medium": 2, "info": 3}
    changes.sort(key=lambda x: (order.get(x["level"], 9), str(x["asin"])))
    return changes


def render_text(changes, asin_count, as_of, failed):
    if not changes:
        line = "【跟卖监控】%d 个 ASIN 卖家数与价格均无变化（%s）" % (asin_count, as_of)
        if failed:
            line += "；%d 个没拉到数据" % len(failed)
        return line
    lines = ["【跟卖监控】%d 条变化（%s）" % (len(changes), as_of)]
    for c in changes[:6]:
        lines.append("[%s] %s %s — %s" % (c["level"], c["asin"], c["msg"], c["action"]))
    if len(changes) > 6:
        lines.append("…等 %d 条，详见报告" % len(changes))
    return "\n".join(lines)


def render_html(changes, asin_count, as_of, failed, prev_date):
    counts = {lv: sum(1 for c in changes if c["level"] == lv)
              for lv in ("critical", "high", "medium", "info")}
    cards = [
        {"label": "监控 ASIN", "value": str(asin_count)},
        {"label": "critical", "value": str(counts["critical"]),
         "note": "真的被跟卖/压价" if counts["critical"] else "无"},
        {"label": "high", "value": str(counts["high"]), "note": "扩散中" if counts["high"] else "无"},
        {"label": "对比基准", "value": prev_date or "首次", "note": "上一次快照日期"},
    ]
    if changes:
        rows = [[c["asin"], c["kind"], '<span class="tag %s">%s</span>' % (
            {"critical": "bad", "high": "warn", "medium": "warn", "info": "good"}.get(c["level"], "warn"),
            c["level"]), c["msg"], c["action"]] for c in changes]
        inner = hr.table(["ASIN", "类型", "级别", "变化", "先做什么"], rows)
    else:
        inner = "<p>所有监控 ASIN 的卖家数与价格都没有变化。</p>"
    if failed:
        inner += ('<p style="font-size:12px;color:#b45309;margin-top:8px">'
                  '这几个没拉到数据（数据源缺字段或额度）：%s</p>' % "、".join(failed))

    body = (hr.banner("有 %d 条 critical 要处理" % counts["critical"] if counts["critical"]
                      else ("有 %d 条 high 值得看" % counts["high"] if counts["high"]
                            else "跟卖情况正常"),
                      "bad" if counts["critical"] else ("warn" if counts["high"] else "good"))
            + c.kpi_cards(cards)
            + hr.section("变化清单（按严重度排序）", inner))
    footer = ("口径：卖家精灵 Keepa 采集的 sellers（该 ASIN 在售 offer 数，含 FBA/FBM）与 price；"
              "购物车卖家 ID 历史数据源拿不到，所以「购物车易主」只能间接推断。"
              "监控名单 config/watchlist.json；对比基准 %s。" % (prev_date or "首次运行"))
    html = hr.render(title="跟卖监控", subtitle="我们自己的 ASIN", meta="数据截至 %s" % as_of,
                     banner_html="", body_html=body, footer=footer)
    return hr.save(html, OUT_DIR / ("%s_hijack.html" % as_of))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--fetch", action="store_true", help="卖家精灵拉最新快照（花额度）")
    ap.add_argument("--asins", default="", help="逗号分隔的 ASIN，覆盖 profiles 里的名单")
    ap.add_argument("--asins-file", default="",
                    help="从文件读 ASIN（一行一个）；配合 find_suspects.py 的待查清单，"
                         "只查销量异常的那几个")
    ap.add_argument("--format", default="html", choices=["html", "text"])
    ap.add_argument("--limit", type=int, default=0,
                    help="只跑名单前 N 个（0=全部）。用于分级监控：出单主力每天盯，"
                         "其余每周一次，省卖家精灵额度")
    args = ap.parse_args()

    if args.asins_file:
        fp = Path(args.asins_file)
        if not fp.is_absolute():
            fp = ROOT / fp
        if not fp.exists():
            print("清单文件不存在：%s（先跑 scripts/find_suspects.py）" % fp)
            return 2
        asins = [x.strip().upper() for x in fp.read_text(encoding="utf-8").splitlines()
                 if x.strip()]
        if not asins:
            print("清单是空的——没有疑似跟卖的 SKU，不用查")
            return 0
    elif args.asins_file:
        fp = Path(args.asins_file)
        if not fp.is_absolute():
            fp = ROOT / fp
        if not fp.exists():
            print("清单文件不存在：%s（先跑 scripts/find_suspects.py）" % fp)
            return 2
        asins = [x.strip().upper() for x in fp.read_text(encoding="utf-8").splitlines()
                 if x.strip()]
        if not asins:
            print("清单是空的——没有疑似跟卖的 SKU，不用花额度")
            return 0
    elif args.asins:
        asins = [a.strip().upper() for a in args.asins.split(",") if a.strip()]
    else:
        asins = [x["asin"] for x in load_watchlist()]
    if not asins:
        print("没有可监控的 ASIN：要么填 config/watchlist.json 的 our_asins，要么 --asins")
        return 2
    if args.limit and len(asins) > args.limit:
        print("分级监控：只跑前 %d 个（名单共 %d 个）" % (args.limit, len(asins)))
        asins = asins[:args.limit]

    snaps = load_all_snapshots()
    if args.fetch:
        print("拉取 %d 个 ASIN 的快照…" % len(asins))
        cur = fetch_snapshots(asins)
        prev = snaps[-1] if snaps else None
    else:
        if len(snaps) < 2:
            print("快照不足（需要至少 2 天才能比变化）。先跑一次 --fetch，明天再跑。")
            return 2
        cur, prev = snaps[-1], snaps[-2]

    as_of = cur.get("date") or dt.date.today().isoformat()
    changes = diff(prev, cur)
    prev_date = (prev or {}).get("date")
    failed = cur.get("failed") or []
    n = len(cur.get("items") or {})

    if args.format == "text":
        print(render_text(changes, n, as_of, failed))
    else:
        out = render_html(changes, n, as_of, failed, prev_date)
        print("✓ 跟卖监控 → %s" % out)
        print(render_text(changes, n, as_of, failed))

    return 1 if any(c["level"] == "critical" for c in changes) else 0


if __name__ == "__main__":
    sys.exit(main())
