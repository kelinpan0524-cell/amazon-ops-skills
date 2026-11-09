#!/usr/bin/env python3
"""竞品与跟卖监控：卖家精灵拉快照 → 与上次对比 → 只报"变了什么"。

用法：
  python3 skills/amz-competitor-watch/scripts/run.py
  python3 skills/amz-competitor-watch/scripts/run.py --format text
  python3 skills/amz-competitor-watch/scripts/run.py --no-fetch   # 用已存快照重算（省额度）

数据：config/competitors.json 里的竞对 ASIN 清单（人工维护）；快照落 data/raw/competitor/ 不进 git。
退出码：有跟卖嫌疑/竞品断货/大幅降价 → 1；否则 0。
"""
import argparse
import datetime as dt
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent.parent / "_shared"))
import html_report as hr  # noqa: E402
import mcp_client as mc   # noqa: E402
import metrics as m       # noqa: E402

ROOT = HERE.parent.parent.parent
WATCH_JSON = ROOT / "config" / "competitors.json"
RAW_DIR = ROOT / "data" / "raw" / "competitor"
OUT_DIR = ROOT / "data" / "reports" / "competitor"
MARKETPLACE = "US"

# 变化阈值（占位，可调）
PRICE_DROP_ALERT = 0.08      # 竞品降价 >8% → 关注（抢单开始）
PRICE_UP_ALERT = 0.08        # 竞品提价 >8% → 机会（留出价格空间）
REVIEW_JUMP = 30             # 评论单周增 >30 → 对手在推
RATING_DROP = 0.2            # 评分单周掉 >0.2 → 对手出问题
SELLER_GROWTH_ALERT = 1      # 卖家数增加 ≥1 家 → 跟卖嫌疑（我方 ASIN 出现别的卖家）

# 变化的影响排序（高→低），用于「变化清单」按影响置顶（SKILL.md 承诺过）
KIND_WEIGHT = {"疑似断货": 0, "跟卖嫌疑": 1, "降价": 2, "提价": 3,
               "评论暴增": 4, "评分下滑": 5}


def parse_asins(text):
    """从 competitors.md 抽 ASIN（B0 开头 10 位）+ 行内备注。"""
    out = []
    for line in text.splitlines():
        for asin in re.findall(r"\bB0[A-Z0-9]{8}\b", line):
            note = line.replace(asin, "").strip(" |-\t")[:60]
            out.append({"asin": asin, "note": note})
    seen, uniq = set(), []
    for a in out:
        if a["asin"] not in seen:
            seen.add(a["asin"])
            uniq.append(a)
    return uniq


def snapshot_path(day=None):
    return RAW_DIR / ("%s.json" % (day or dt.date.today().isoformat()))


def load_prev_snapshot(today_path):
    """找上一个快照（按文件名日期倒序，跳过今天）。"""
    if not RAW_DIR.exists():
        return None, None
    files = sorted([p for p in RAW_DIR.glob("*.json") if p.name != today_path.name],
                   key=lambda p: p.name, reverse=True)
    for f in files:
        try:
            return json.loads(f.read_text(encoding="utf-8")), f.stem
        except json.JSONDecodeError:
            continue
    return None, None


def fetch_snapshots(asin_list):
    """调卖家精灵 asin.detail（一次最多 20 个）。

    seller_count 是可选字段：asin.detail 只返回主卖家，不保证给卖家总数。
    字段缺失时记 None，跟卖检测会跳过该 ASIN（在报告里说明），
    绝不拿"主卖家存在"冒充"只有一家在卖"。
    """
    client = mc.sellersprite_client()
    out = {}
    for i in range(0, len(asin_list), 20):
        batch = asin_list[i:i + 20]
        res = client.call_tool("asin.detail", {
            "marketplace": MARKETPLACE, "asins": batch,
            "includeFields": ["asin", "title", "brand", "price", "rating",
                              "reviewCount", "bsr", "seller"],
        })
        for item in (res.get("items") or []):
            if item.get("resultStatus") == "success":
                seller = item.get("seller") or {}
                out[item["asin"]] = {
                    "title": item.get("title", ""),
                    "brand": item.get("brand", ""),
                    "price": m.num(item.get("price")),
                    "rating": m.num(item.get("rating")),
                    "reviews": m.num(item.get("reviewCount")),
                    "bsr": m.num(item.get("bsr")),
                    "seller": seller.get("name", ""),
                    # 卖家总数：服务端可能给 offerCount / sellerCount，取到才用
                    "seller_count": m.num(item.get("offerCount") or item.get("sellerCount")
                                          or item.get("sellerNum")),
                }
    return out


def diff(prev, cur):
    """生成变化清单（按影响排序，最重要的在最前）。"""
    changes = []
    for asin, now in cur.items():
        old = (prev or {}).get(asin)
        if not old:
            continue

        # 价格：涨跌用两个不同阈值（跌=威胁，涨=机会），都各自生效
        p_now, p_old = now.get("price"), old.get("price")
        if p_now and p_old and p_old > 0:
            d = (p_now - p_old) / p_old
            if d <= -PRICE_DROP_ALERT:
                changes.append({
                    "asin": asin, "kind": "降价", "level": "high",
                    "msg": "价格 $%.2f → $%.2f（%+.0f%%）" % (p_old, p_now, d * 100),
                    "action": "评估是否跟价：先看自己盈亏线，别盲目跟",
                })
            elif d >= PRICE_UP_ALERT:
                changes.append({
                    "asin": asin, "kind": "提价", "level": "medium",
                    "msg": "价格 $%.2f → $%.2f（%+.0f%%）" % (p_old, p_now, d * 100),
                    "action": "留出价格空间，可考虑跟涨或加广告抢位",
                })

        r_now, r_old = now.get("reviews"), old.get("reviews")
        if r_now is not None and r_old is not None and r_now - r_old >= REVIEW_JUMP:
            changes.append({"asin": asin, "kind": "评论暴增", "level": "medium",
                            "msg": "评论 %d → %d（+%d）" % (r_old, r_now, r_now - r_old),
                            "action": "查对手是否在上活动/站外，同步检查我们的评价节奏"})

        s_now, s_old = now.get("rating"), old.get("rating")
        if s_now is not None and s_old is not None and s_old - s_now >= RATING_DROP:
            changes.append({"asin": asin, "kind": "评分下滑", "level": "medium",
                            "msg": "评分 %.1f → %.1f" % (s_old, s_now),
                            "action": "对手口碑出问题 = 我们的转化机会，可加广告承接"})

        # 跟卖嫌疑：卖家数变多（这是「我方 ASIN 被别人跟卖」的核心信号）
        seller_now, seller_old = now.get("seller_count"), old.get("seller_count")
        if (seller_now is not None and seller_old is not None
                and seller_now - seller_old >= SELLER_GROWTH_ALERT):
            changes.append({"asin": asin, "kind": "跟卖嫌疑", "level": "high",
                            "msg": "卖家数 %d → %d（新增 %d 家）"
                                   % (seller_old, seller_now, seller_now - seller_old),
                            "action": "先确认是不是同条件跟卖（不是变体）；有品牌备案走商标举报，"
                                      "没有就先 test buy 取证——本技能只发现不代举报"})

        # 对手断货：卖家信息从有到无
        if not now.get("seller") and old.get("seller"):
            changes.append({"asin": asin, "kind": "疑似断货", "level": "high",
                            "msg": "卖家信息消失（原 %s）" % old.get("seller"),
                            "action": "机会窗口：加广告/提价试探，同时确认是不是临时缺货"})

    # 按影响排序（SKILL.md 承诺「变化最大的置顶」）
    changes.sort(key=lambda ch: (KIND_WEIGHT.get(ch["kind"], 9), ch["asin"]))
    return changes


def build_report(asin_list, cur, prev, prev_day, changes, today):
    alert_n = sum(1 for ch in changes if ch["level"] == "high")
    if not prev:
        banner_txt, level = "首次快照（%d 个 ASIN），下次起会报变化" % len(cur), "warn"
    elif alert_n:
        banner_txt, level = "%d 项重要变化需处理（共 %d 个 ASIN 在跟）" % (alert_n, len(cur)), "bad"
    elif changes:
        banner_txt, level = "%d 项一般变化，可周会过一眼" % len(changes), "warn"
    else:
        banner_txt, level = "本周 0 项变化（跟了 %d 个 ASIN）" % len(cur), "good"

    rows = []
    for a in asin_list:
        asin = a["asin"]
        now = cur.get(asin)
        if not now:
            rows.append([asin, a["note"] or "-", "未取到", "-", "-", "-", "-"])
            continue
        old = (prev or {}).get(asin) or {}
        def dlt(k, fmt):
            v, o = now.get(k), old.get(k)
            if v is None:
                return "-"
            if o is None:
                return fmt % v
            return "%s → %s" % (fmt % o, fmt % v) if v != o else fmt % v
        rows.append([asin, a["note"] or now.get("brand") or "-",
                     dlt("price", "$%.2f"), dlt("rating", "%.1f"),
                     dlt("reviews", "%d"), dlt("bsr", "%d"), now.get("seller") or "-"])

    body = hr.banner(banner_txt, level)
    if changes:
        body += hr.section("变化清单（按影响排序）", hr.table(
            ["ASIN", "类型", "变化", "该怎么办"],
            [[ch["asin"], ch["kind"], ch["msg"], ch["action"]] for ch in changes]))
    body += hr.section("全量快照", hr.table(
        ["ASIN", "备注/品牌", "价格", "评分", "评论数", "BSR", "卖家"], rows,
        align_right={2, 3, 4, 5}))
    body += hr.section("⚠ 读这份清单要知道", '<ul class="plain">'
                       "<li>竞品数据是<b>卖家精灵估算值</b>（价格较准，销量/BSR 为估算），只看趋势不当精确数。</li>"
                       "<li>不抓亚马逊页面：数据来自第三方采集，可能滞后 1–2 天。</li>"
                       "<li>跟卖嫌疑只做<b>发现</b>：举报/投诉走人工流程（品牌备案 → Trademark 举报）。</li>"
                       "<li>竞品变价不等于我们必须跟：先看自己盈亏线（成本未校准前只作参考）。</li></ul>")
    footer = ("数据源：卖家精灵 MCP（%s 站）· 对比基准：%s · 清单：config/competitors.json · "
              "阈值：本脚本常量（PRICE_DROP_ALERT 等）。" % (MARKETPLACE, prev_day or "首次快照"))
    return hr.render(title="竞品与跟卖监控", subtitle="%d 个 ASIN · 只报变化" % len(cur),
                     meta="快照日 %s" % today, banner_html="", body_html=body, footer=footer)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--format", default="html", choices=["html", "text"])
    ap.add_argument("--no-fetch", action="store_true", help="不调 MCP，用已存快照重算")
    args = ap.parse_args()

    if not WATCH_JSON.exists():
        print("缺 config/competitors.json（从 competitors.example.json 复制一份再填）")
        return 0
    try:
        watch = (json.loads(WATCH_JSON.read_text(encoding="utf-8")) or {}).get("watch") or []
    except (OSError, ValueError):
        watch = []
    asin_list = [{"asin": (w.get("asin") or "").strip().upper(),
                  "note": (w.get("note") or "")[:50]}
                 for w in watch if isinstance(w, dict) and w.get("asin")]
    if not asin_list:
        print("【needs_data】config/competitors.json 里还没有竞品 ASIN（B0 开头 10 位）——"
              "先人工填 5-10 个再跑；本技能不编竞品。")
        return 0

    today = dt.date.today().isoformat()
    path = snapshot_path(today)
    prev, prev_day = load_prev_snapshot(path)

    if args.no_fetch and path.exists():
        cur = json.loads(path.read_text(encoding="utf-8"))
    else:
        cur = fetch_snapshots([a["asin"] for a in asin_list])
        RAW_DIR.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(cur, ensure_ascii=False, indent=1), encoding="utf-8")

    changes = diff(prev, cur)
    if args.format == "text":
        if not changes:
            print("【竞品】%d 个 ASIN 本周 0 项变化。" % len(cur))
        else:
            print("【竞品】%d 项变化：" % len(changes))
            for ch in changes[:6]:
                print("  [%s] %s %s — %s" % (ch["level"], ch["asin"], ch["msg"], ch["action"]))
        return 1 if any(ch["level"] == "high" for ch in changes) else 0

    out = hr.save(build_report(asin_list, cur, prev, prev_day, changes, today),
                  OUT_DIR / ("%s_watch.html" % today))
    print("✓ 竞品监控 → %s" % out)
    print("  %d 个 ASIN，%d 项变化（%d 项重要）" % (
        len(cur), len(changes), sum(1 for ch in changes if ch["level"] == "high")))
    return 1 if any(ch["level"] == "high" for ch in changes) else 0


if __name__ == "__main__":
    sys.exit(main())
