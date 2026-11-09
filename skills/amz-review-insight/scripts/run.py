#!/usr/bin/env python3
"""竞品差评分析：拉竞品的 1-3 星评论，归类问题，出改款建议。

## 为什么这个技能价值最高
自己产品的差评只能改自己；**竞品的差评是免费的选品调研**——
一个 200 条评论里 40 条说"装不上"的品，说明它的 fitment 数据烂，
你做一个装得上同款就能抢客。这比自己猜需求靠谱得多。

参考开源做法：nexscope 的 `amazon-review-analyzer`、
liangdabiao 的 sorftime 差评分析、APIClaw 的 `review insights`。
共同点：**按问题类型归类**，不是简单列评论。

## 判什么（关键词归类，不依赖大模型）
装不上 / 尺寸不对 / 质量问题 / 物流破损 / 描述不符 / 价格贵 / 其他
每类给：条数、占比、代表评论 2 条

## 用法
  python3 skills/amz-review-insight/scripts/run.py --asins B0XXX,B0YYY --fetch
  python3 skills/amz-review-insight/scripts/run.py --asins B0XXX            # 用已存快照
  python3 skills/amz-review-insight/scripts/run.py --asins B0XXX --format text

**花额度**：每个 ASIN 一次 `asin.review.list`（标准版，最多 100 条）。
看竞品用标准版够了，别用 extended（2 分钟、额度高）。

退出码：抓到差评 → 1；抓不到 → 0；没数据 → 2。
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
RAW_DIR = ROOT / "data" / "raw" / "review-insight"
OUT_DIR = ROOT / "data" / "reports" / "review-insight"
MARKETPLACE = "US"

# 问题归类：按关键词命中（英文评论）。顺序有意义——先判最具体的
CATEGORIES = [
    ("装不上/适配错", [
        r"\bnot fit\b", r"\bdoesn'?t fit\b", r"\bdidn'?t fit\b", r"\bwrong part\b",
        r"\bwrong item\b", r"\bno fit\b", r"\bnot compatible\b", r"\bwrong size\b",
        r"\bdoes not fit\b", r"\bwon'?t fit\b"]),
    ("尺寸/规格不对", [
        r"\btoo (big|small|short|long|large)\b", r"\bsize\b", r"\bdimension\b",
        r"\bmetric\b", r"\bdiameter\b",
        # 单位要连数字一起匹配："12mm" 里 mm 前面是数字，\bmm\b 匹配不到
        # （2026-11-04 测试踩到："Listed as 12mm but measured 10mm" 归不出类）
        r"\d+\s*(?:mm|cm|inches?|inch|in)\b", r"\b(?:mm|cm|inches?|inch)\b"]),
    ("质量问题", [
        r"\bbroke\b", r"\bbroken\b", r"\bcracked\b", r"\bcheap(ly)?\b", r"\bflimsy\b",
        r"\bpoor quality\b", r"\bdefective\b", r"\bfailed\b", r"\brusted\b",
        r"\bwore out\b", r"\bnoisy\b"]),
    ("物流/包装", [
        r"\barrived\b", r"\bshipping\b", r"\bpackag", r"\bmissing\b", r"\bdamaged\b",
        r"\bnever (came|arrived|received)\b", r"\blate\b"]),
    ("描述不符", [
        r"\bnot as described\b", r"\bmisleading\b", r"\bdifferent from\b",
        r"\bpicture\b", r"\bphoto\b", r"\badvertis"]),
    ("价格/性价比", [
        r"\boverpriced\b", r"\bexpensive\b", r"\bnot worth\b", r"\bwaste of money\b",
        r"\bcheaper\b"]),
    ("安装困难", [
        r"\bhard to install\b", r"\bdifficult\b", r"\bno instruction", r"\binstructions\b",
        r"\bconfusing\b"]),
]


def normalize(r):
    star = r.get("star") or r.get("rating")
    try:
        star = int(float(star))
    except (TypeError, ValueError):
        star = None
    return {"star": star, "title": str(r.get("title") or "")[:120],
            "content": str(r.get("content") or r.get("review") or "")[:900],
            "date": str(r.get("date") or "")[:10]}


def fetch(asins, limit=100):
    client = mc.sellersprite_client()
    out, failed = {}, []
    for asin in asins:
        try:
            res = client.call_tool("asin.review.list", {
                "marketplace": MARKETPLACE, "asin": asin,
                "limit": limit, "sort": "DATE_DESC"})
            raw = res.get("reviews") if isinstance(res, dict) else []
            if isinstance(raw, dict):
                raw = raw.get("reviews") or raw.get("items") or []
            revs = [normalize(r) for r in (raw or []) if isinstance(r, dict)]
            out[asin] = revs
            bad = [r for r in revs if r["star"] is not None and r["star"] <= 3]
            print("  · %s %d 条评论，其中差评 %d 条" % (asin, len(revs), len(bad)))
        except (mc.MCPError, OSError, TimeoutError) as e:
            failed.append(asin)
            print("  ! %s 拉取失败：%s" % (asin, str(e)[:80]))
        import time
        time.sleep(1.0)
    snap = {"date": dt.date.today().isoformat(), "items": out, "failed": failed}
    if out:
        RAW_DIR.mkdir(parents=True, exist_ok=True)
        (RAW_DIR / ("%s.json" % snap["date"])).write_text(
            json.dumps(snap, ensure_ascii=False, indent=2), encoding="utf-8")
    return snap


def classify(text):
    """一条评论命中哪类问题。返回类别名或 None。"""
    low = text.lower()
    for name, pats in CATEGORIES:
        for p in pats:
            if re.search(p, low):
                return name
    return None


def analyze(snap):
    """按 ASIN 统计差评问题分布。"""
    out = []
    for asin, revs in (snap.get("items") or {}).items():
        bad = [r for r in revs if r["star"] is not None and r["star"] <= 3]
        if not bad:
            continue
        buckets = {}
        for r in bad:
            cat = classify((r.get("title") or "") + " " + (r.get("content") or ""))
            key = cat or "其他"
            buckets.setdefault(key, []).append(r)
        rows = sorted(buckets.items(), key=lambda kv: -len(kv[1]))
        out.append({"asin": asin, "total": len(revs), "bad": len(bad),
                    "rate": len(bad) / len(revs) if revs else 0,
                    "buckets": [(k, v) for k, v in rows]})
    out.sort(key=lambda x: -x["bad"])
    return out


ADVICE = {
    "装不上/适配错": "这个品的 fitment 数据有问题。你要做同款的话，把适配车型年份写全、加装配示意图——"
                     "直接吃掉它的客诉流量。",
    "尺寸/规格不对": "图片和实测尺寸对不上。做同款时把关键尺寸标在图上（带单位换算 mm/inch）。",
    "质量问题": "材质/工艺有短板。查评论具体说哪里坏，做同款时在那处加成本。",
    "物流/包装": "包装或发货有问题。做同款时改进包装，能直接拿「开箱完整」当卖点。",
    "描述不符": "listing 夸大。做同款时描述保守一点、图片实拍，退货率会低。",
    "价格/性价比": "客户觉得贵。这个价位有空间，但要看它的采购成本能不能压下来。",
    "安装困难": "装配体验差。做同款时配图文说明书或短视频，是差异化点。",
    "其他": "人工读一下这几条，机器归不出类。",
}


def render_text(results):
    if not results:
        return "【竞品差评】拉到的评论里没有 1-3 星的"
    lines = ["【竞品差评分析】%d 个 ASIN 有差评：" % len(results)]
    for r in results[:5]:
        top = r["buckets"][0]
        lines.append("  %s：%d/%d 差评（%.0f%%），主要是「%s」%d 条"
                     % (r["asin"], r["bad"], r["total"], r["rate"] * 100, top[0], len(top[1])))
    return "\n".join(lines)


def render_html(results, as_of):
    if not results:
        return None
    cards = [
        {"label": "分析 ASIN", "value": str(len(results))},
        {"label": "差评总数", "value": str(sum(r["bad"] for r in results))},
        {"label": "平均差评率", "value": "%.0f%%" % (
            sum(r["bad"] for r in results) / max(sum(r["total"] for r in results), 1) * 100)},
        {"label": "最集中的问题", "value": (results[0]["buckets"][0][0] if results else "-")[:10]},
    ]
    parts = []
    for r in results:
        trs = []
        for cat, items in r["buckets"]:
            sample = items[0]
            trs.append([cat, str(len(items)),
                        "%.0f%%" % (len(items) / r["bad"] * 100),
                        ((sample.get("title") or sample.get("content") or "")[:70]),
                        ADVICE.get(cat, "")[:80]])
        parts.append(
            '<p style="margin:14px 0 6px"><b>%s</b>：%d 条评论里 %d 条差评（%.0f%%）</p>'
            % (r["asin"], r["total"], r["bad"], r["rate"] * 100)
            + hr.table(["问题类型", "条数", "占比", "代表评论", "你能怎么用"],
                       trs, align_right={1, 2}))
    body = (hr.banner("竞品的差评就是你的机会", "good")
            + c.kpi_cards(cards)
            + hr.section("按 ASIN 拆解", "".join(parts))
            + hr.section("⚠ 怎么读", '<ul class="plain">'
                         '<li>归类靠关键词匹配（英文），中文评论和反讽会归错，抽样读几条确认</li>'
                         '<li>评论是卖家精灵采集的，不是亚马逊全量；比例为「样本内占比」不是总体</li>'
                         '<li><b>「你能怎么用」是给选品/改款的方向，不是自动改 Listing</b></li>'
                         '<li>差评多不等于不能做——看是哪一类：fitment 错是机会，质量差是门槛</li>'
                         '</ul>'))
    footer = ("口径：卖家精灵 asin.review.list（标准版，最多 100 条/ASIN）· %s 站 · "
              "只分析 1-3 星 · 数据截至 %s" % (MARKETPLACE, as_of))
    html = hr.render(title="竞品差评分析", subtitle="从别人的差评里找改款/选品机会",
                     meta="数据截至 %s" % as_of, banner_html="",
                     body_html=body, footer=footer)
    return hr.save(html, OUT_DIR / ("%s_review-insight.html" % as_of))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--asins", required=True, help="竞品 ASIN，逗号分隔")
    ap.add_argument("--fetch", action="store_true", help="拉最新评论（花额度）")
    ap.add_argument("--limit", type=int, default=100, help="每个 ASIN 拉多少条（最大 100）")
    ap.add_argument("--format", default="html", choices=["html", "text"])
    args = ap.parse_args()

    asins = [a.strip().upper() for a in args.asins.split(",") if a.strip()]
    if not asins:
        print("--asins 不能为空")
        return 2

    if args.fetch:
        snap = fetch(asins, min(args.limit, 100))
    else:
        files = sorted(RAW_DIR.glob("*.json")) if RAW_DIR.exists() else []
        if not files:
            print("没有快照（先跑一次 --fetch）")
            return 2
        snap = json.loads(files[-1].read_text(encoding="utf-8"))

    results = analyze(snap)
    as_of = snap.get("date") or dt.date.today().isoformat()
    if args.format == "text":
        print(render_text(results))
    else:
        out = render_html(results, as_of)
        if out:
            print("✓ 竞品差评分析 → %s" % out)
        print(render_text(results))
    return 1 if results else 0


if __name__ == "__main__":
    sys.exit(main())
