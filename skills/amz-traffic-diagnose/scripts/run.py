#!/usr/bin/env python3
"""流量诊断：某个 ASIN 的流量从哪来、哪些词有曝光没转化、该补什么词。

## 为什么需要
"这个品卖不动"有很多原因，最常见的是**流量结构有问题**：
- 只靠广告词撑着，自然词一个没有 → 广告一停就死
- 流量词很多但转化差 → 不是流量问题，是 listing/价格问题
- 核心词被别人占着 → 要补长尾词

这个技能把这三件事分开说，而不是笼统说"流量不好"。

## 数据来源
卖家精灵 `keyword.asin.list`（品找词）：返回该 ASIN 的流量关键词，
每个词带搜索量、购买量、购买率、竞争度、PPC 竞价、流量占比。

## 用法
  python3 skills/amz-traffic-diagnose/scripts/run.py --asin B0D62SYW8S --fetch
  python3 skills/amz-traffic-diagnose/scripts/run.py --asin B0D62SYW8S --format text
  python3 skills/amz-traffic-diagnose/scripts/run.py --asin B0D62SYW8S --top 30

退出码：有"高曝光低转化"的词 → 1；否则 0；没数据 → 2。
"""
import argparse
import datetime as dt
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent.parent / "_shared"))
import chartlets as c     # noqa: E402
import html_report as hr  # noqa: E402
import mcp_client as mc   # noqa: E402

ROOT = HERE.parent.parent.parent
RAW_DIR = ROOT / "data" / "raw" / "traffic"
OUT_DIR = ROOT / "data" / "reports" / "traffic"
MARKETPLACE = "US"

# 判"高曝光低转化"：搜索量大但购买率明显低于该 ASIN 的中位
HIGH_VOLUME_PCT = 0.6      # 搜索量在前 40%
LOW_CVR_FACTOR = 0.5       # 购买率低于中位的 50%


def num(v, default=None):
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def fetch(asin, limit=50):
    client = mc.sellersprite_client()
    res = client.call_tool("keyword.asin.list", {
        "marketplace": MARKETPLACE, "asins": [asin],
        "page": {"cursor": 0, "size": min(limit, 100)}})
    raw = res.get("items") if isinstance(res, dict) else []
    if isinstance(raw, dict):
        raw = raw.get("items") or raw.get("keywords") or []
    rows = []
    for r in (raw or []):
        if not isinstance(r, dict):
            continue
        rows.append({
            "keyword": str(r.get("keyword") or "")[:80],
            "searches": num(r.get("searchVolume") or r.get("searches"), 0),
            "purchases": num(r.get("purchases"), 0),
            "cvr": num(r.get("purchaseRate")),
            "traffic_share": num(r.get("trafficShare")),
            "competition": num(r.get("products")),
            "ppc": num(r.get("ppc") or r.get("bid")),
            "types": r.get("trafficWordTypes") or [],
        })
    snap = {"date": dt.date.today().isoformat(), "asin": asin, "keywords": rows}
    if rows:
        RAW_DIR.mkdir(parents=True, exist_ok=True)
        (RAW_DIR / ("%s_%s.json" % (asin, snap["date"]))).write_text(
            json.dumps(snap, ensure_ascii=False, indent=2), encoding="utf-8")
    return snap


def load_snap(asin):
    files = sorted(RAW_DIR.glob("%s_*.json" % asin)) if RAW_DIR.exists() else []
    if not files:
        return None
    return json.loads(files[-1].read_text(encoding="utf-8"))


def analyze(snap, top=30):
    """分出：核心流量词 / 高曝光低转化 / 有广告标 / 自然词覆盖。"""
    rows = sorted(snap.get("keywords") or [], key=lambda x: -(x.get("searches") or 0))[:top]
    if not rows:
        return None
    cvrs = [r["cvr"] for r in rows if r.get("cvr")]
    median_cvr = sorted(cvrs)[len(cvrs) // 2] if cvrs else None
    total_share = sum((r.get("traffic_share") or 0) for r in rows) or None

    weak = []
    if median_cvr:
        cut = median_cvr * LOW_CVR_FACTOR
        for r in rows:
            if (r.get("searches") or 0) >= (rows[0]["searches"] * (1 - HIGH_VOLUME_PCT)) \
                    and r.get("cvr") is not None and r["cvr"] < cut:
                weak.append(r)

    ad_words = [r for r in rows if any("ADS" in str(t) for t in (r.get("types") or []))]
    organic = [r for r in rows if not any("ADS" in str(t) for t in (r.get("types") or []))]

    # 流量集中度：前 3 个词占多少（>60% 说明太依赖少数词）
    top3_share = sum((r.get("traffic_share") or 0) for r in rows[:3])
    return {"rows": rows, "median_cvr": median_cvr, "weak": weak,
            "ad_words": ad_words, "organic": organic,
            "top3_share": top3_share, "total_share": total_share}


def diagnose_text(asin, a):
    lines = ["【流量诊断】%s" % asin]
    if not a:
        return lines[0] + "\n没有流量词数据（卖家精灵词库未收录该 ASIN）"
    lines.append("  流量词 %d 个，前 3 个占流量 %.0f%%%s" % (
        len(a["rows"]), a["top3_share"] * 100,
        "（过度依赖少数词）" if a["top3_share"] > 0.6 else ""))
    lines.append("  广告词 %d 个 / 自然词 %d 个%s" % (
        len(a["ad_words"]), len(a["organic"]),
        "（自然流量几乎为零，广告一停就死）" if len(a["organic"]) <= 2 else ""))
    if a["weak"]:
        lines.append("  高曝光低转化 %d 个：" % len(a["weak"]))
        for r in a["weak"][:4]:
            lines.append("    %s（搜 %s 次，购买率 %.2f%%）→ 图片/价格/评分跟不上"
                         % (r["keyword"][:36], int(r["searches"]),
                            (r["cvr"] or 0) * 100))
    return "\n".join(lines)


def render_html(asin, a, as_of):
    if not a:
        return None
    cards = [
        {"label": "流量词", "value": str(len(a["rows"]))},
        {"label": "前 3 词占流量", "value": "%.0f%%" % (a["top3_share"] * 100),
         "note": ">60% 说明过度依赖"},
        {"label": "广告词 / 自然词", "value": "%d / %d" % (len(a["ad_words"]), len(a["organic"]))},
        {"label": "高曝光低转化", "value": str(len(a["weak"])), "note": "要查图片/价格"},
    ]
    trs = []
    for i, r in enumerate(a["rows"][:20], 1):
        types = ",".join(str(t) for t in (r.get("types") or [])[:2]) or "自然"
        trs.append([str(i), r["keyword"][:40], str(int(r["searches"])),
                    ("%.2f%%" % (r["cvr"] * 100)) if r.get("cvr") else "-",
                    ("%.0f%%" % (r["traffic_share"] * 100)) if r.get("traffic_share") else "-",
                    str(int(r["competition"])) if r.get("competition") else "-",
                    ("$%.1f" % r["ppc"]) if r.get("ppc") else "-", types])
    body = (hr.banner(("有 %d 个词有曝光没转化" % len(a["weak"])) if a["weak"]
                      else "流量结构没看出明显问题", "warn" if a["weak"] else "good")
            + c.kpi_cards(cards)
            + hr.section("流量词 Top20", hr.table(
                ["#", "关键词", "月搜索量", "购买率", "流量占比", "竞品数", "PPC", "来源"],
                trs, align_right={2, 3, 4, 5, 6}))
            + hr.section("⚠ 怎么读", '<ul class="plain">'
                         '<li><b>前 3 词占比 >60%</b>：太依赖少数词，其中任何一个掉排名都会断崖</li>'
                         '<li><b>自然词只有 1-2 个</b>：全靠广告，广告一停就没流量</li>'
                         '<li><b>高曝光低转化</b>：不是流量问题，是图片/价格/评分接不住——先修 listing</li>'
                         '<li>搜索量/购买率都是<b>估算值</b>，只能横向比，别当绝对值</li>'
                         '</ul>'))
    footer = ("口径：卖家精灵 keyword.asin.list（品找词）· %s 站 · 数据截至 %s · "
              "估算数据，只能做相对判断" % (MARKETPLACE, as_of))
    html = hr.render(title="流量诊断", subtitle=asin,
                     meta="数据截至 %s" % as_of, banner_html="",
                     body_html=body, footer=footer)
    return hr.save(html, OUT_DIR / ("%s_traffic.html" % asin))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--asin", required=True)
    ap.add_argument("--fetch", action="store_true", help="拉最新（花额度）")
    ap.add_argument("--top", type=int, default=30)
    ap.add_argument("--format", default="html", choices=["html", "text"])
    args = ap.parse_args()

    asin = args.asin.strip().upper()
    snap = fetch(asin, max(args.top, 20)) if args.fetch else load_snap(asin)
    if not snap:
        print("没有数据（先跑一次 --fetch）")
        return 2
    a = analyze(snap, args.top)
    as_of = snap.get("date") or dt.date.today().isoformat()
    if args.format == "text":
        print(diagnose_text(asin, a))
    else:
        out = render_html(asin, a, as_of)
        if out:
            print("✓ 流量诊断 → %s" % out)
        print(diagnose_text(asin, a))
    return 1 if (a and a["weak"]) else 0


if __name__ == "__main__":
    sys.exit(main())
