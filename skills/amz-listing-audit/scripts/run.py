#!/usr/bin/env python3
"""Listing 体检与优化建议：按 CDQ 框架给每个 ASIN 打分，指出该改哪儿。

框架参考开源的 amazon-listing-doctor（buluslan/amazon-listing-doctor）：
6 个维度加权——结构化属性 30%、标题 25%、变体 20%、图片 15%、五点 5%、A+ 5%。
权重是社区经验值，不是亚马逊官方口径，只能横向比自己的 ASIN。

**只诊断不改写**：不动标题、不动图片、不动 Listing。

用法：
  python3 skills/amz-listing-audit/scripts/run.py            # 用 sales_daily 里的标题
  python3 skills/amz-listing-audit/scripts/run.py --top 20   # 只看销售额前 20 个
  python3 skills/amz-listing-audit/scripts/run.py --format text

数据：
- **标题**：自动从 sales_daily 的 product_name 取（现在就有，不用另导）
- **五点/A+/图片/结构化属性**：要导 listing_current 表；没有的维度标「未检查」，
  不给 0 分也不给满分——假装查过比不查更糟。
- **OE 号/年款/车型**：有 sku_master 才查（汽配命门），没有就跳过并说清楚。

退出码：有 P1 硬伤 → 1；否则 0；没数据 → 2。
"""
import argparse
import datetime as dt
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent.parent / "_shared"))
import chartlets as c     # noqa: E402
import html_report as hr  # noqa: E402
import metrics as m       # noqa: E402

ROOT = HERE.parent.parent.parent
OUT_DIR = ROOT / "data" / "reports" / "listing"
T = m.load_thresholds()["listing"]
F = m.load_thresholds()["fitment"]

# CDQ 六维权重（社区经验值）
WEIGHTS = {"结构化属性": 0.30, "标题": 0.25, "变体": 0.20,
           "图片": 0.15, "五点": 0.05, "A+": 0.05}
TITLE_MOBILE_CUT = 75     # 移动端搜索结果大约从这之后截断
TITLE_MAX = 200
TITLE_MIN = 40

ABSOLUTE_WORDS = ("best", "100%", "guaranteed", "perfect", "no.1", "number one",
                  "#1", "top rated", "best seller", "miraculous")
SCENE_WORDS = ("front", "rear", "upper", "lower", "driver", "passenger", "left", "right")
AUDIENCE_WORDS = ("for", "fit", "compatible", "replacement", "direct fit")
GOAL_WORDS = ("repair", "replace", "fix", "upgrade", "restore", "suspension", "steering")
CONSTRAINT_WORDS = ("with", "w/o", "without", "including", "excludes", "years", "except")
CAR_BRANDS = ("nissan", "toyota", "honda", "ford", "chevy", "chevrolet", "bmw",
              "audi", "vw", "volkswagen", "subaru", "mazda", "hyundai", "kia",
              "jeep", "dodge", "gmc", "buick", "cadillac", "lexus", "infiniti",
              "acura", "mitsubishi", "volvo", "mercedes", "porsche", "tesla")


def load_titles(top=0):
    """从 sales_daily 提 ASIN + 标题（按销售额排序取前 N 个）。"""
    agg = {}
    for r in m.load("sales_daily"):
        asin = (r.get("asin") or "").strip()
        # 领星拉的是 product_name；手工导的表历史上用过 title，两种都认
        title = (r.get("product_name") or r.get("title") or "").strip()
        if not asin or not title:
            continue
        a = agg.setdefault(asin, {"asin": asin, "title": title, "rev": 0.0,
                                  "sku": r.get("sku") or "", "shop": r.get("shop") or ""})
        a["rev"] += m.num(r.get("revenue")) or 0
        if len(title) > len(a["title"]):
            a["title"] = title
    rows = sorted(agg.values(), key=lambda x: -x["rev"])
    return rows[:top] if top else rows


def top_skus_by_sales(sales, n=5):
    """按销量汇总到唯一 SKU（同 SKU 多行折叠），取销量最高的 n 个。

    保留这个名字是因为 test_listing_audit.py 用它钉住「重复行要折叠」这个行为。
    """
    agg = {}
    for r in sales:
        k = r.get("sku") or r.get("asin")
        if not k:
            continue
        agg[k] = agg.get(k, 0.0) + m._f(r.get("units"))
    return [k for k, _ in sorted(agg.items(), key=lambda kv: kv[1], reverse=True)[:n]]


def score_title(title):
    """标题维度打分（0-100）+ 问题清单。只判能从文字本身判断的项。"""
    t, low, n = title.strip(), title.strip().lower(), len(title.strip())
    pts, issues, good = 0.0, [], []

    # 车标硬阻断：命中就单独标 HOLD，不参与打分
    logo_hits = m.brand_logo_hold(title, context="text")

    # 长度 40 分
    if n < TITLE_MIN:
        issues.append("标题只有 %d 字符（建议 ≥%d）" % (n, TITLE_MIN))
        pts += 20 * (n / TITLE_MIN)
    elif n > TITLE_MAX:
        issues.append("标题 %d 字符超过 %d 上限" % (n, TITLE_MAX))
        pts += 20
    else:
        pts += 40
        if n > TITLE_MOBILE_CUT:
            good.append("标题 %d 字符：移动端前 %d 字符后会被截断，核心词要往前放"
                        % (n, TITLE_MOBILE_CUT))
        else:
            good.append("标题 %d 字符，移动端能完整显示" % n)

    # 绝对化用语 25 分
    hit = [w for w in ABSOLUTE_WORDS if w in low]
    if hit:
        issues.append("含绝对化用语 %s（易被下架/广告拒登）" % "、".join(hit[:3]))
    else:
        pts += 25

    # COSMO 意图四要素 25 分
    cover = []
    for name, words in (("场景", SCENE_WORDS), ("适配", AUDIENCE_WORDS),
                        ("解决什么", GOAL_WORDS), ("限制", CONSTRAINT_WORDS)):
        if any(w in low for w in words):
            cover.append(name)
    pts += 25 * len(cover) / 4
    if len(cover) < 2:
        issues.append("意图要素只覆盖 %d/4（场景/适配/解决什么/限制），"
                      "COSMO 下容易被判「不知道给谁用」" % len(cover))
    else:
        good.append("意图要素覆盖 %d/4：%s" % (len(cover), "、".join(cover)))

    # 车型信息 10 分（汽配命门）
    if any(w in low for w in CAR_BRANDS):
        pts += 10
    else:
        issues.append("标题没写车型品牌——汽配靠「适配什么车」被搜到，这条很致命")

    return round(min(pts, 100), 0), issues, good, logo_hits


def fitment_stats(rows):
    total = len(rows)
    if not total:
        return None
    return {"total": total,
            "oe": sum(1 for r in rows if str(r.get("oe_number", "")).strip()) / total,
            "year": sum(1 for r in rows
                        if str(r.get("year_from", "")).strip()
                        and str(r.get("year_to", "")).strip()) / total,
            "model": sum(1 for r in rows if str(r.get("vehicle_model", "")).strip()) / total}


def build_row(item, extra):
    t_score, issues, good, logo_hits = score_title(item["title"])
    if logo_hits:
        issues.insert(0, "HOLD：标题命中车标触发词 %s——侵权硬阻断，移除前不得发布"
                      % "、".join(logo_hits))

    dims = {"标题": (t_score, True)}
    if "bullets_count" in extra:
        bc = m._f(extra.get("bullets_count"))
        dims["五点"] = (min(bc / 5 * 100, 100), True)
        if bc < T["bullet_count_min"]:
            issues.append("五点只有 %d 条（建议写满 5 条）" % bc)
    if "has_a_plus" in extra:
        has = str(extra.get("has_a_plus")).lower() in ("1", "true", "yes", "y")
        dims["A+"] = (100 if has else 0, True)
        if not has:
            issues.append("没有 A+ 内容（转化率通常差 3-10%）")
    if "image_count" in extra:
        ic = m._f(extra.get("image_count"))
        dims["图片"] = (min(ic / 7 * 100, 100), True)
        if ic < 7:
            issues.append("主图+副图只有 %d 张（建议 7 张）" % ic)

    got = sum(WEIGHTS[k] * v[0] for k, v in dims.items() if v[1])
    maxw = sum(WEIGHTS[k] for k in dims if dims[k][1])
    cdq = round(got / maxw, 0) if maxw else None
    unchecked = [k for k in WEIGHTS if k not in dims]

    p1 = t_score < 60 or bool(logo_hits) or any("致命" in i for i in issues)
    level = "P1" if p1 else ("P2" if issues else "OK")
    return {"asin": item["asin"], "sku": item["sku"], "shop": item["shop"],
            "title": item["title"], "cdq": cdq, "title_score": t_score,
            "issues": issues, "good": good, "unchecked": unchecked, "level": level}


def render_html(results, fit_st, as_of):
    p1 = [r for r in results if r["level"] == "P1"]
    p2 = [r for r in results if r["level"] == "P2"]
    scored = [r["cdq"] for r in results if r["cdq"] is not None]
    avg = sum(scored) / len(scored) if scored else 0
    unchecked_all = sorted({u for r in results for u in r["unchecked"]})

    cards = [
        {"label": "体检 ASIN", "value": str(len(results))},
        {"label": "平均 CDQ", "value": "%.0f" % avg, "note": "只算已检查维度"},
        {"label": "P1 硬伤", "value": str(len(p1)), "note": "影响曝光/转化"},
        {"label": "P2 待改", "value": str(len(p2))},
    ]

    def tbl(rows):
        trs = []
        for r in rows:
            trs.append([
                r["asin"], (r["sku"] or "")[:16],
                "%.0f" % r["cdq"] if r["cdq"] is not None else "-",
                "%.0f" % r["title_score"],
                '<span class="tag %s">%s</span>' % ("bad" if r["level"] == "P1" else "warn", r["level"]),
                (r["title"] or "")[:60],
                "<br>".join(r["issues"][:2]) or "—",
            ])
        return hr.table(["ASIN", "SKU", "CDQ", "标题分", "级别", "标题（前 60 字）", "问题"],
                        trs, align_right={2, 3})

    inner = ""
    if p1:
        inner += "<p style='margin:8px 0 4px'><b>P1 硬伤（先改这些）</b></p>" + tbl(p1)
    if p2:
        inner += "<p style='margin:14px 0 4px'><b>P2 待改</b></p>" + tbl(p2)
    if not p1 and not p2:
        inner = "<p>所有 ASIN 的标题都没查出硬伤。</p>"

    fit_html = ""
    if fit_st:
        fit_html = hr.section("汽配命门（OE 号 / 年款 / 车型）", hr.table(
            ["指标", "填写率", "门槛", "状态"],
            [["OE 号", "%.0f%%" % (fit_st["oe"] * 100), "%.0f%%" % (F["min_oe_ratio"] * 100),
              '<span class="tag %s">%s</span>' % (
                  "good" if fit_st["oe"] >= F["min_oe_ratio"] else "bad",
                  "合格" if fit_st["oe"] >= F["min_oe_ratio"] else "要补")],
             ["年款区间", "%.0f%%" % (fit_st["year"] * 100), "—", "—"],
             ["车型", "%.0f%%" % (fit_st["model"] * 100), "—", "—"]],
            align_right={1}))
    else:
        fit_html = ('<p style="font-size:12.5px;color:#b45309">没查到 sku_master，'
                    'OE 号/年款/车型未检查——对汽配来说这是最重要的适配数据，'
                    '缺它所有「装不装得上」的判断都做不了。</p>')

    unchecked = ('<p style="font-size:11.5px;color:#6b7280;margin-top:10px;line-height:1.75">'
                 'CDQ 权重（结构化属性 30%%/标题 25%%/变体 20%%/图片 15%%/五点 5%%/A+ 5%%）'
                 '是社区经验值，不是亚马逊官方口径，只能横向比自己的 ASIN。<br>'
                 '<b>本次未检查：%s</b>——要导 <code>listing_current</code> 表才有数据，'
                 '报告里不给分也不假装通过。标题判断只基于文字本身，'
                 '五点有没有说服力、A+ 图好不好看仍需人工复核。<br>'
                 '依据：<a href="https://github.com/buluslan/amazon-listing-doctor" '
                 'target="_blank" style="color:#2563eb">amazon-listing-doctor</a>'
                 % ("、".join(unchecked_all) or "无"))

    body = (hr.banner(("%d 个 ASIN 有硬伤" % len(p1)) if p1
                      else ("%d 个可以再优化" % len(p2) if p2 else "标题维度全部合格"),
                      "bad" if p1 else ("warn" if p2 else "good"))
            + c.kpi_cards(cards)
            + fit_html
            + hr.section("内容项体检", inner + unchecked))
    footer = ("口径：标题取自 sales_daily 的 product_name · 只诊断不改写 · "
              "绝对化用语与长度规则见脚本顶部 · 数据截至 %s" % as_of)
    html = hr.render(title="Listing 体检与优化建议",
                     subtitle="CDQ 框架 · 只出建议不改 Listing",
                     meta="数据截至 %s" % as_of, banner_html="",
                     body_html=body, footer=footer)
    return hr.save(html, OUT_DIR / ("%s_listing.html" % as_of))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--top", type=int, default=0, help="只看销售额前 N 个 ASIN")
    ap.add_argument("--format", default="html", choices=["html", "text"])
    args = ap.parse_args()

    titles = load_titles(args.top)
    if not titles:
        print("没有可体检的数据：sales_daily 里没有 ASIN+标题。"
              "先跑 scripts/fetch_sku.py --days 3")
        return 2

    # listing_current 是可选补充
    extra_by_asin = {}
    for r in m.load("listing_current"):
        a = (r.get("asin") or "").strip()
        if a:
            extra_by_asin[a] = r

    master = m.load("sku_master")
    fit_st = fitment_stats(master) if master else None

    results = [build_row(x, extra_by_asin.get(x["asin"], {})) for x in titles]
    p1 = [r for r in results if r["level"] == "P1"]
    p2 = [r for r in results if r["level"] == "P2"]

    if args.format == "text":
        print("【Listing 体检】%d 个 ASIN：P1 硬伤 %d / P2 待改 %d"
              % (len(results), len(p1), len(p2)))
        for r in (p1 + p2)[:8]:
            print("  [%s] %s CDQ %s | %s" % (
                r["level"], r["asin"],
                "%.0f" % r["cdq"] if r["cdq"] is not None else "-",
                r["issues"][0] if r["issues"] else "-"))
        if not p1 and not p2:
            print("  标题维度全部合格")
    else:
        out = render_html(results, fit_st, dt.date.today().isoformat())
        print("✓ Listing 体检 → %s" % out)
        print("  P1 %d / P2 %d / 共 %d 个 ASIN" % (len(p1), len(p2), len(results)))
    return 1 if p1 else 0


if __name__ == "__main__":
    sys.exit(main())
