#!/usr/bin/env python3
"""评论监控：盯自己 ASIN 的新评论，重点抓 1-3 星差评。

用法：
  python3 skills/amz-review-watch/scripts/run.py --fetch        # 拉最新评论（花额度）
  python3 skills/amz-review-watch/scripts/run.py                # 用已存快照比对
  python3 skills/amz-review-watch/scripts/run.py --format text

数据：config/watchlist.json 的 our_asins（与跟卖监控同一份，都是自己的产品）；
快照落 data/raw/review/，按 (asin, 日期, 标题) 去重。
退出码：有新差评（1-3 星）→ 1；否则 0；没数据 → 2。

为什么只报"新出现"的：评论页每次拉回来都是同一批老评论，
不去重的话每天报同样的差评，人会直接无视这个告警。
"""
import argparse
import datetime as dt
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent.parent / "_shared"))
import chartlets as c     # noqa: E402
import html_report as hr  # noqa: E402
import mcp_client as mc   # noqa: E402

ROOT = HERE.parent.parent.parent
WATCH_JSON = ROOT / "config" / "watchlist.json"
RAW_DIR = ROOT / "data" / "raw" / "review"
OUT_DIR = ROOT / "data" / "reports" / "review"
MARKETPLACE = "US"
BAD_STAR_MAX = 3          # 1-3 星算差评（汽配类 1-2 星多是装不上/尺寸不对）
FETCH_LIMIT = 20          # 每个 ASIN 每次拉最近 N 条


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


def parse_asins(text):
    out, seen = [], set()
    for line in text.splitlines():
        for asin in re.findall(r"\bB0[A-Z0-9]{8}\b", line):
            if asin not in seen:
                seen.add(asin)
                out.append(asin)
    return out


def _review_key(r):
    """评论去重键：日期 + 标题前 40 字（评论没有稳定的 id）。"""
    return "%s|%s" % (str(r.get("date") or "")[:10],
                      str(r.get("title") or "")[:40])


def normalize(r):
    star = r.get("star") or r.get("rating") or r.get("stars")
    try:
        star = int(float(star))
    except (TypeError, ValueError):
        star = None
    return {
        "star": star,
        "date": str(r.get("date") or r.get("reviewDate") or "")[:10],
        "title": str(r.get("title") or "")[:120],
        "content": str(r.get("content") or r.get("review") or "")[:800],
        "sku": str(r.get("sku") or r.get("variation") or "")[:60],
    }


def _save_partial(items, failed):
    """每拉完一个 ASIN 就落盘：20 个 ASIN 要跑一分多钟，
    中途任何一个请求挂住（2026-11-04 实测卡在第 20 个），
    原来"循环结束才写"就等于整轮白跑。"""
    snap = {"date": dt.date.today().isoformat(), "marketplace": MARKETPLACE,
            "items": items, "failed": failed}
    if items:
        RAW_DIR.mkdir(parents=True, exist_ok=True)
        (RAW_DIR / ("%s.json" % snap["date"])).write_text(
            json.dumps(snap, ensure_ascii=False, indent=2), encoding="utf-8")
    return snap


def fetch_reviews(asins):
    client = mc.sellersprite_client()
    items, failed = {}, []
    for asin in asins:
        try:
            res = client.call_tool("asin.review.list", {
                "marketplace": MARKETPLACE, "asin": asin,
                "limit": FETCH_LIMIT, "sort": "DATE_DESC"})
            raw = res.get("reviews") if isinstance(res, dict) else []
            if isinstance(raw, dict):
                raw = raw.get("reviews") or raw.get("items") or []
            norm = [normalize(r) for r in (raw or []) if isinstance(r, dict)]
            items[asin] = norm
            print("  · %s %d 条评论（最近 %s）" % (
                asin, len(norm), norm[0]["date"] if norm else "-"))
        except (mc.MCPError, OSError, TimeoutError) as e:
            failed.append(asin)
            print("  ! %s 拉取失败：%s" % (asin, str(e)[:80]))
        _save_partial(items, failed)     # 每个 ASIN 后立刻落盘
        import time
        time.sleep(1.0)
    return _save_partial(items, failed)


def load_snapshots():
    out = []
    if not RAW_DIR.exists():
        return out
    for f in sorted(RAW_DIR.glob("*.json")):
        try:
            d = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if d.get("items"):
            out.append(d)
    return out


def diff(prev, cur):
    """找出「这次才有」的评论；其中 1-3 星单独标出来。"""
    seen = set()
    for asin, revs in ((prev or {}).get("items") or {}).items():
        for r in revs:
            seen.add((asin, _review_key(r)))
    new_bad, new_all = [], []
    for asin, revs in (cur.get("items") or {}).items():
        for r in revs:
            k = (asin, _review_key(r))
            if k in seen:
                continue
            r = dict(r, asin=asin)
            new_all.append(r)
            if r.get("star") is not None and r["star"] <= BAD_STAR_MAX:
                new_bad.append(r)
    new_bad.sort(key=lambda x: (x.get("star") or 5, x.get("date") or ""))
    return new_bad, new_all


def render_text(new_bad, new_all, as_of, total_asin):
    if not new_all:
        return "【评论监控】%d 个 ASIN 没有新评论（%s）" % (total_asin, as_of)
    if not new_bad:
        return "【评论监控】%d 条新评论，都是 4-5 星（%s）" % (len(new_all), as_of)
    lines = ["【评论监控】%d 条新差评（%s）" % (len(new_bad), as_of)]
    for r in new_bad[:5]:
        lines.append("★%d %s｜%s｜%s" % (
            r["star"], r["asin"], (r.get("title") or "")[:30],
            (r.get("content") or "")[:60].replace("\n", " ")))
    return "\n".join(lines)


def render_html(new_bad, new_all, as_of, total_asin, prev_date):
    cards = [
        {"label": "监控 ASIN", "value": str(total_asin)},
        {"label": "新评论", "value": str(len(new_all))},
        {"label": "其中差评(≤%d星)" % BAD_STAR_MAX, "value": str(len(new_bad)),
         "note": "要有人看" if new_bad else "无"},
        {"label": "对比基准", "value": prev_date or "首次", "note": "上次快照日期"},
    ]
    if new_all:
        rows = []
        for r in sorted(new_all, key=lambda x: (x.get("star") or 5, x.get("date") or "")):
            star = r.get("star") or 0
            rows.append([
                r["asin"], "★%d" % star if star else "—",
                r.get("date") or "", (r.get("title") or "")[:40],
                '<span class="tag %s">%s</span>' % (
                    "bad" if star and star <= BAD_STAR_MAX else "good",
                    "差评" if star and star <= BAD_STAR_MAX else "好评"),
                (r.get("content") or "")[:160]])
        inner = hr.table(["ASIN", "星级", "日期", "标题", "类型", "内容"], rows)
    else:
        inner = "<p>所有监控 ASIN 都没有新评论。</p>"
    note = ('<p style="font-size:11.5px;color:#6b7280;margin-top:8px;line-height:1.75">'
            '只报「这次才有」的评论：评论页每次拉回来都是同一批老评论，'
            '不去重会天天报同样的差评，人就无视了。'
            '差评判定：≤%d 星。汽配类 1-2 星多是「装不上/尺寸不对」，'
            '这类要优先核查 fitment 而不是话术。</p>' % BAD_STAR_MAX)
    body = (hr.banner(("有 %d 条新差评要处理" % len(new_bad)) if new_bad
                      else ("%d 条新评论，无差评" % len(new_all) if new_all else "没有新评论"),
                      "bad" if new_bad else "good")
            + c.kpi_cards(cards)
            + hr.section("新评论清单（差评排前面）", inner + note))
    footer = ("口径：卖家精灵 asin.review.list · %s 站 · 每个 ASIN 最近 %d 条；"
              "对比基准 %s。评论没有稳定 id，按「日期+标题前 40 字」去重。"
              % (MARKETPLACE, FETCH_LIMIT, prev_date or "首次运行"))
    html = hr.render(title="评论监控", subtitle="我们自己的 ASIN · 只报新出现的",
                     meta="数据截至 %s" % as_of, banner_html="",
                     body_html=body, footer=footer)
    return hr.save(html, OUT_DIR / ("%s_review.html" % as_of))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--fetch", action="store_true", help="卖家精灵拉最新评论（花额度）")
    ap.add_argument("--asins", default="", help="逗号分隔 ASIN，覆盖 profiles 名单")
    ap.add_argument("--format", default="html", choices=["html", "text"])
    ap.add_argument("--limit", type=int, default=0,
                    help="只跑名单前 N 个（0=全部）。用于分级监控：出单主力每天盯，"
                         "其余每周一次，省卖家精灵额度")
    args = ap.parse_args()

    if args.asins:
        asins = [a.strip().upper() for a in args.asins.split(",") if a.strip()]
    else:
        asins = [x["asin"] for x in load_watchlist()]
    if not asins:
        print("没有可监控的 ASIN：填 config/watchlist.json 的 our_asins 或 --asins")
        return 2
    if args.limit and len(asins) > args.limit:
        print("分级监控：只跑前 %d 个（名单共 %d 个）" % (args.limit, len(asins)))
        asins = asins[:args.limit]

    snaps = load_snapshots()
    if args.fetch:
        print("拉取 %d 个 ASIN 的评论…" % len(asins))
        cur = fetch_reviews(asins)
        prev = snaps[-1] if snaps else None
    else:
        if len(snaps) < 2:
            print("快照不足（需要至少 2 天）。先跑一次 --fetch，明天再跑。")
            return 2
        cur, prev = snaps[-1], snaps[-2]

    as_of = cur.get("date") or dt.date.today().isoformat()
    new_bad, new_all = diff(prev, cur)
    prev_date = (prev or {}).get("date")
    n = len(cur.get("items") or {})

    if args.format == "text":
        print(render_text(new_bad, new_all, as_of, n))
    else:
        out = render_html(new_bad, new_all, as_of, n, prev_date)
        print("✓ 评论监控 → %s" % out)
        print(render_text(new_bad, new_all, as_of, n))
    return 1 if new_bad else 0


if __name__ == "__main__":
    sys.exit(main())
