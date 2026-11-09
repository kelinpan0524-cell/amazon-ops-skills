#!/usr/bin/env python3
"""每日经营简报（HTML 图文版）：昨天发生了什么、今天要处理什么。

用法：
  python3 skills/amz-sku-daily/scripts/run.py [--date YYYY-MM-DD]

输出：data/reports/daily/<最新完整日>_daily.html
口径：USD 原值不换算、下单口径；长尾款日波动大，日级异动只作线索，
     经营判断以周/月报（amz-week-month-review）为准。
缺数据直说，不估算。
"""
import argparse
import datetime as dt
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent.parent / "_shared"))
import chartlets as c   # noqa: E402
import html_report as hr  # noqa: E402
import metrics as m     # noqa: E402
import shopdata as sd   # noqa: E402
import sku_table as st  # noqa: E402

ROOT = HERE.parent.parent.parent
OUT_DIR = ROOT / "data" / "reports" / "daily"


def day_shift(d, days):
    return (dt.date.fromisoformat(d) - dt.timedelta(days=days)).isoformat()


def year_ago(d):
    """去年同日（2-29 回退 2-28）。"""
    try:
        return dt.date.fromisoformat(d).replace(year=dt.date.fromisoformat(d).year - 1).isoformat()
    except ValueError:
        return "%s-02-28" % (int(d[:4]) - 1)


def shop_series():
    """shop -> {date: row}，含全部历史（同比要用去年）。"""
    idx = {}
    for r in m.load("shop_daily"):
        d = m.row_date(r)
        if d and r.get("shop"):
            idx.setdefault(r["shop"], {})[d] = r
    return idx


def sum_shop(idx, day, key):
    vals = [sd.val(by[day], key) for by in idx.values() if day in by]
    vals = [v for v in vals if v is not None]
    return sum(vals) if vals else None


def pct_delta(cur, old):
    if cur is None or old in (None, 0):
        return None
    return (cur - old) / old


def fmt_pct(v, signed=True):
    if v is None:
        return "—"
    return ("%+.1f%%" if signed else "%.1f%%") % (v * 100)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", default="", help="数据日（默认最新完整日）")
    args = ap.parse_args()

    idx = shop_series()
    all_days = sorted({d for by in idx.values() for d in by})
    if not all_days:
        print("没有 shop_daily 数据（先跑 scripts/fetch_lingxing.py）")
        return 2
    today = dt.date.today().isoformat()
    full_days = [d for d in all_days if d != today]
    as_of = args.date or (full_days[-1] if full_days else all_days[-1])

    rev = sum_shop(idx, as_of, "revenue")
    units = sum_shop(idx, as_of, "units")
    spend = sum_shop(idx, as_of, "spend")
    prev_d, week_d, yago_d = day_shift(as_of, 1), day_shift(as_of, 7), year_ago(as_of)
    rev_d = pct_delta(rev, sum_shop(idx, prev_d, "revenue"))
    rev_w = pct_delta(rev, sum_shop(idx, week_d, "revenue"))
    rev_y = pct_delta(rev, sum_shop(idx, yago_d, "revenue"))
    yoy_missing = sum_shop(idx, yago_d, "revenue") is None

    cards = [
        {"label": "销售额(USD)", "value": "$%s" % c._fmt(rev), "delta": rev_d},
        {"label": "销量(件)", "value": c._fmt(units), "delta": pct_delta(units, sum_shop(idx, prev_d, "units"))},
        {"label": "广告花费(USD)", "value": "$%s" % c._fmt(spend), "delta": pct_delta(spend, sum_shop(idx, prev_d, "spend")), "delta_good": False},
        {"label": "周环比（上周同日）", "value": fmt_pct(rev_w), "note": "长尾款主要看这个"},
        {"label": "同比（去年同日）", "value": fmt_pct(rev_y),
         "note": "日粒度仅90天，同比见月报" if yoy_missing else "去年同日有数据"},
    ]

    cmp_rows = [
        ["销售额", "$%s" % c._fmt(rev), fmt_pct(rev_d), fmt_pct(rev_w), fmt_pct(rev_y)],
        ["销量(件)", c._fmt(units), fmt_pct(pct_delta(units, sum_shop(idx, prev_d, "units"))),
         fmt_pct(pct_delta(units, sum_shop(idx, week_d, "units"))),
         fmt_pct(pct_delta(units, sum_shop(idx, yago_d, "units")))],
        ["广告花费", "$%s" % c._fmt(spend), fmt_pct(pct_delta(spend, sum_shop(idx, prev_d, "spend"))),
         fmt_pct(pct_delta(spend, sum_shop(idx, week_d, "spend"))),
         fmt_pct(pct_delta(spend, sum_shop(idx, yago_d, "spend")))],
    ]

    # 近 14 天趋势（多店合计）
    trend_days = [d for d in full_days if d <= as_of][-14:]
    labels = [d[5:] for d in trend_days]
    rev_series = [{"name": "销售额", "values": [sum_shop(idx, d, "revenue") for d in trend_days], "color": c.BLUE}]

    # 异常清单（结构化 → 表格）：库存急件 Top8 + 广告烧钱 + 销量异动
    findings = []
    inv = m.load("inventory_daily")
    sales_all = m.load("sales_daily")
    inv_dates = m.table_dates(inv)
    inv_day = inv_dates[-1] if inv_dates else as_of
    u28 = m.recent_units_by_sku(sales_all, 28)
    crit = []
    for r in inv:
        if m.row_date(r) != inv_day:
            continue
        avail = m.num(r.get("fba_available"))
        if avail is None:
            continue
        k = r.get("sku") or r.get("asin")
        dos = m.days_of_supply(avail, u28.get(k, 0.0))
        if dos is not None and dos < 10:
            crit.append((dos, k, r.get("asin") or "", r.get("shop") or "", avail))
    crit.sort()
    for dos, sku, asin, shop, avail in crit[:8]:
        findings.append(["🔴 断货急件", sku, asin, shop, "可售 %.1f 天（FBA %.0f）" % (dos, avail), "立即补货"])
    st_rows, _ = st.sku_daily_rows(day=as_of)
    for s in sorted([x for x in st_rows if x.get("has_ads") and (x.get("spend") or 0) >= 15 and not x.get("orders")],
                    key=lambda x: -(x.get("spend") or 0))[:5]:
        findings.append(["🟠 广告烧钱", s["sku"], s.get("asin") or "", s.get("shop") or "",
                         "花费 $%.0f · 0 单" % s["spend"], "先查搜索词/竞价"])
    for s in sorted([x for x in st_rows if x.get("drop")], key=lambda x: -(x.get("prev_units") or 0))[:8]:
        findings.append(["🟡 销量骤跌", s["sku"], s.get("asin") or "", s.get("shop") or "",
                         "%.0f→%.0f 件" % (s.get("prev_units") or 0, s.get("units") or 0),
                         "日波动大，先看周趋势再归因"])
    for s in sorted([x for x in st_rows if x.get("spike")], key=lambda x: -(x.get("units") or 0))[:5]:
        findings.append(["🟢 销量骤涨", s["sku"], s.get("asin") or "", s.get("shop") or "",
                         "%.0f→%.0f 件" % (s.get("prev_units") or 0, s.get("units") or 0), "核对是否断货回补/促销"])

    # SKU 当日明细（Top30 按销售额）
    sku_rows = sorted(st_rows, key=lambda x: -(x.get("revenue") or 0))[:30]
    detail = [[s["sku"], s.get("asin") or "", s.get("shop") or "",
               "{:,.0f}".format(s.get("units") or 0),
               "$%s" % c._fmt(s.get("revenue") or 0),
               "$%s" % c._fmt(s.get("spend") or 0),
               "—" if s.get("fba") is None else "{:,.0f}".format(s["fba"]),
               "—" if s.get("dos") is None else "%.1f" % s["dos"]] for s in sku_rows]

    banner = "日报 %s：销售额 $%s（日环比 %s · 周环比 %s · 同比 %s）" % (
        as_of, c._fmt(rev), fmt_pct(rev_d), fmt_pct(rev_w), fmt_pct(rev_y))
    level = "good" if (rev_w or 0) >= 0 else "warn"

    body = (
        hr.banner(banner, level)
        + c.kpi_cards(cards)
        + hr.section("同环比一览（USD 原值）",
                     hr.table(["指标", "当日", "日环比(昨日)", "周环比(上周同日)", "同比(去年同日)"],
                              cmp_rows, align_right={1, 2, 3, 4})
                     + "<p style='color:#6b7280;font-size:13px'>我们是长尾款，单日波动大："
                       "日环比只看线索，<b>经营判断以周/月报为准</b>。日粒度历史仅 90 天，去年同日不可得；年度同比请看月报。</p>")
        + hr.section("近 14 天销售额趋势", c.line_chart(labels, rev_series, title="多店合计销售额（USD/日）", y_fmt="money"))
        + hr.section("今天要处理的重点（异常清单，%d 条）" % len(findings),
                     hr.table(["类型", "SKU 编码", "ASIN", "店铺", "数据", "建议动作"], findings)
                     if findings else "<p>无异常。</p>")
        + hr.section("当日 SKU 明细 Top30（按销售额）",
                     hr.table_filterable(hr.table(
                         ["SKU 编码", "ASIN", "店铺", "销量", "销售额USD", "广告USD", "FBA可售", "可售天数"],
                         detail, align_right={3, 4, 5, 6, 7}), "daily-sku")
                     if detail else "<p>当前日期没有可用的 SKU 明细；店铺汇总仍保留，不能用空表冒充已核验。</p>")
        + hr.methodology([
            ["日环比", "(当日 − 昨日) ÷ 昨日；昨日为 0 或缺数据时显示 —"],
            ["周环比", "(当日 − 上周同日) ÷ 上周同日；长尾款主看口径"],
            ["同比", "(当日 − 去年同日) ÷ 去年同日；领星日粒度仅保留 90 天，去年同日不可得时显示 —（不估算）；年度同比见月报（月度接口可回溯 24 个月）"],
            ["断货急件", "可售天数 = FBA 可售 ÷ 近 28 天等效日均销量；<10 天立即补货"],
            ["广告烧钱", "当日花费 ≥$15 且 0 订单；$15 = 单件毛利量级，先查搜索词"],
            ["销量异动", "较前日 ≥50% 为骤跌/≥100% 为骤涨；日级只作线索，以周/月报确认"],
            ["金额口径", "领星 USD 原值，不做汇率换算；下单口径，店铺组多站合并"],
        ])
    )
    footer = ("数据源 shop_daily / sales_daily / ads_asin_daily / inventory_daily（USD）。"
              "表格支持点表头排序、搜索、导出 Excel（浏览器打开时生效）。")
    html = hr.render(title="每日经营简报（%s）" % as_of,
                     subtitle="多店合计 · USD",
                     meta="生成日 %s · 数据截至 %s" % (today, as_of),
                     banner_html="", body_html=body, footer=footer)
    out = hr.save(html, OUT_DIR / ("%s_daily.html" % as_of))
    print(out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
