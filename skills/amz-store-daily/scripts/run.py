#!/usr/bin/env python3
"""单店铺经营日报（HTML 图表版）：读 shop_daily.csv 出单文件 SVG 报告。

用法：
  python3 skills/amz-store-daily/scripts/run.py              # 全部店铺组
  python3 skills/amz-store-daily/scripts/run.py --shop shop_a

口径：领星 USD、下单口径、店铺组多站点合并；不展示利润（未校准红线）。
今天的数据领星尚未产齐时，自动回退到最近一个完整日并标注。
"""
import argparse
import datetime as dt
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent.parent / "_shared"))
import chartlets as c   # noqa: E402
import html_report as hr  # noqa: E402
import metrics as m     # noqa: E402
import shopdata as sd    # noqa: E402
import benchmarks as bm  # noqa: E402  （基准/目标/红线）

ROOT = HERE.parent.parent.parent
SHOPS_JSON = ROOT / "config" / "shops.json"
OUT_DIR = ROOT / "data" / "reports" / "shop"
WINDOW_DAYS = 30


def load_rows(shop):
    rows = [r for r in m.load("shop_daily") if r.get("shop") == shop]
    dated = [(m.row_date(r), r) for r in rows]
    dated = [(d, r) for d, r in dated if d]
    dated.sort(key=lambda kv: kv[0])
    return dated


# 数值读取统一走共享层（缺数返回 None）
val = sd.val


def build_shop_report(shop, cfg):
    dated = load_rows(shop)
    display = cfg.get("display") or shop
    if not dated:
        return None, "没有 %s 的 shop_daily 数据（先跑 scripts/fetch_lingxing.py）" % shop

    # 最新完整日：跳过「今天」（领星当日数据未产齐），取最近一个非今天的日期
    today = dt.date.today().isoformat()
    full_days = [(d, r) for d, r in dated if d != today]
    use_today = not full_days
    target = dated[-1] if use_today else full_days[-1]
    latest_d, latest = target
    prev = None
    prev_candidates = [r for d, r in dated if d < latest_d]
    if prev_candidates:
        prev = prev_candidates[-1]
    cutoff = (dt.date.fromisoformat(latest_d) - dt.timedelta(days=WINDOW_DAYS)).isoformat()
    window = [(d, r) for d, r in dated if cutoff < d <= latest_d]

    def money(v):
        return "$%s" % c._fmt(v)

    def pct(v, nd=1):
        if v is None:
            return "缺数据"
        return "%s%%" % c._fmt(v * 100, nd)

    # ---- KPI ----
    def delta_of(key, invert=False):
        cur, old = val(latest, key), (val(prev, key) if prev else None)
        if cur is None or old in (None, 0):
            return None
        return (cur - old) / old

    _base = bm.history_baseline(shop)
    tacos = (val(latest, "spend") / val(latest, "revenue")) if val(latest, "revenue") else None
    cvr = (val(latest, "units") / val(latest, "sessions")) if val(latest, "sessions") else None
    cards = [
        {"label": "销售额(USD)", "value": money(val(latest, "revenue")),
         "delta": delta_of("revenue")},
        {"label": "销量(件)", "value": c._fmt(val(latest, "units")),
         "delta": delta_of("units")},
        {"label": "广告花费", "value": money(val(latest, "spend")),
         "delta": delta_of("spend"), "delta_good": False},
        {"label": "ACOS", "value": pct(val(latest, "acos")),
         "delta": delta_of("acos"), "delta_good": False,
         "note": bm.kpi_note("acos", shop, _base)},
        {"label": "TACOS", "value": pct(tacos), "delta_good": False,
         "note": bm.kpi_note("tacos", shop, _base)},
        {"label": "转化率", "value": pct(cvr, 2), "note": "销量÷会话"},
        {"label": "FBA 可售(件)", "value": c._fmt(val(latest, "fba_available")),
         "note": "仅 FBA 口径"},
    ]

    # ---- 图表数据 ----
    labels = [d[5:] for d, _ in window]  # MM-DD
    rev_series = [{"name": "销售额", "values": [val(r, "revenue") for _, r in window],
                   "color": c.BLUE}]
    units_vals = [val(r, "units") for _, r in window]
    spend_series = [{"name": "广告花费", "values": [val(r, "spend") for _, r in window],
                     "color": c.AMBER}]
    acos_series = [{"name": "ACOS", "values": [val(r, "acos") for _, r in window],
                    "color": c.RED}]

    # ---- 结论条 ----
    rev_d = delta_of("revenue")
    if rev_d is None:
        banner_txt, level = "%s %s：数据已到位（首日无环比）" % (display, latest_d), "warn"
    elif rev_d >= 0.1:
        banner_txt, level = "%s %s：销售额环比 %+.1f%%，表现上行" % (display, latest_d, rev_d * 100), "good"
    elif rev_d <= -0.1:
        banner_txt, level = "%s %s：销售额环比 %+.1f%%，注意下滑归因" % (display, latest_d, rev_d * 100), "bad"
    else:
        banner_txt, level = "%s %s：销售额环比 %+.1f%%，平稳" % (display, latest_d, rev_d * 100), "good"

    # ---- 近 7 日明细表 ----
    table_rows = []
    for d, r in window[-7:][::-1]:
        table_rows.append([
            d,
            c._fmt(val(r, "units")),
            money(val(r, "revenue")),
            money(val(r, "spend")),
            pct(val(r, "acos")),
            c._fmt(val(r, "fba_available")),
        ])

    # 当日 SKU 级明细（销量×广告×库存三表关联；SKU 报告的核心交付）
    import sku_table as st
    sku_rows, sku_day = st.sku_daily_rows(shop=shop, day=latest_d)
    sku_section = hr.section(
        "当日 SKU 明细（%s · %d 个 SKU）" % (sku_day, len(sku_rows)),
        st.sku_table(sku_rows, table_id="shop-sku-%s" % shop) if sku_rows
        else "<p>该日无 SKU 级销售记录（可能当日店休或数据未产齐）。</p>")

    body = (
        hr.banner(banner_txt + ("（今天数据未齐，已回退最近完整日）" if use_today else ""), level)
        + c.kpi_cards(cards)
        + hr.section("近 %d 天趋势" % WINDOW_DAYS,
                     c.line_chart(labels, rev_series, title="销售额趋势（USD/日）", y_fmt="money"))
        + hr.section("销量",
                     c.bar_chart(labels, units_vals, title="销量（件/日）"))
        + hr.section("广告",
                     c.line_chart(labels, spend_series, title="广告花费与 ACOS", y_fmt="money",
                                  y2_series=acos_series, y2_fmt="pct"))
        + hr.section("近 7 日明细",
                     hr.table(["日期", "销量", "销售额", "广告花费", "ACOS", "FBA可售"],
                              table_rows, align_right={1, 2, 3, 4, 5}))
        + sku_section
    )
    body += hr.methodology([
        ("金额口径", "全部 <b>USD（美金）</b>：领星按 USD 折算返回（currency_code=USD），系统不做任何币种换算"),
        ("销售额", "领星「产品表现 total_sum」；下单口径（date_type=purchase）；店铺组多站点合并"),
        ("环比", "（当日 − 前一有数据日）÷ 前一日；前日为 0 或缺数据时不计算，显示「缺数据」"),
        ("ACOS", "广告花费 ÷ 广告销售额；无广告销售时显示「无广告销售」，不当作 0"),
        ("TACOS", "广告花费 ÷ 当日总销售额"),
        ("转化率", "销量（件）÷ 会话数；会话为 0 时不计算"),
        ("结论条阈值", "销售额环比 ≥ +10% 判上行；≤ −10% 判下滑需归因；其间为平稳"),
        ("库存", "仅 FBA 可售（fba_available），不含在途 fba_inbound 与本地/第三方仓"),
        ("SKU 明细", "销售(sales_daily) + 广告(ads_asin_daily) + 库存(inventory_daily) 按「店铺+SKU」对齐；ASIN 可点击跳亚马逊前台"),
        ("不展示项", "毛利/利润未校准，一律不展示"),
    ])
    footer = ("口径：领星产品表现 total_sum · USD · 下单口径 · 店铺组多站合并；"
              "毛利/利润未校准不展示；库存仅 FBA 可售口径（在途/本地仓不在内）。数据源 shop_daily.csv。")
    html = hr.render(
        title="%s 经营日报" % display,
        subtitle="店铺组 %s（%s）" % (shop, cfg.get("sites", "")),
        meta="报告日 %s · 数据截至 %s" % (dt.date.today().isoformat(), latest_d),
        banner_html="", body_html=body, footer=footer)
    out_path = OUT_DIR / shop / ("%s_%s.html" % (latest_d, shop))
    return hr.save(html, out_path), None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--shop", default="", help="店铺组名（缺省全部：config/shops.json）")
    args = ap.parse_args()

    shops = json.loads(SHOPS_JSON.read_text(encoding="utf-8"))["shops"]
    wanted = [s.strip() for s in args.shop.split(",") if s.strip()] or list(shops)
    for s in wanted:
        if s not in shops:
            print("未知店铺组 %r（可选：%s）" % (s, ", ".join(shops)))
            return 2  # 前置条件不满足 → 2（退出码约定见 CONTRIBUTING）

    rendered = 0
    for shop in wanted:
        path, err = build_shop_report(shop, shops[shop])
        if err:
            print("✗ %s：%s" % (shop, err))
            continue
        rendered += 1
        op = shops[shop].get("operator") or ""
        print("✓ %s → %s%s" % (shop, path, ("（运营者：%s）" % op) if op else ""))

    if rendered == 0:
        # 一份都没出就是数据缺失，不能返回 0：定时任务会把漏报当成功
        print("没有生成任何报告：%d 个店铺组全部缺数据（先跑 scripts/fetch_lingxing.py）"
              % len(wanted))
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
