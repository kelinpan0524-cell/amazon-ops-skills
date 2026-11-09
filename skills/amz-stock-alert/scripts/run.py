#!/usr/bin/env python3
"""断货预警：按可售天数排队，急件在前。只看库存与销量，不猜补货在途。"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "_shared"))
import metrics as m  # noqa: E402

T = m.load_thresholds()["stockout"]
P = m.inventory_policy("sku")
W = P["window"]


def main():
    inv = m.latest_rows(m.load("inventory_daily"), 1)
    sales = m.load("sales_daily")
    if not inv:
        print("【数据情况】没有库存表（inventory_daily），先导 FBA 库存报表。")
        return 2
    degraded = m.degraded_tables(["inventory_daily", "sales_daily"])

    if not sales:
        print("【数据情况】没有销量表，算不出日均销量，只能报库存绝对值：")
        for r in inv[:20]:
            print("  - %s 可售 %s" % (r.get("sku") or r.get("asin"), r.get("fba_available")))
        return 2

    # 近 28 天窗口等效销量（去年同期回补段不参与，避免日均被稀释）
    units = m.recent_units_by_sku(sales, W)
    window_days = W  # 固定配置窗口等效（去年同期段不参与）

    rows = []
    for r in inv:
        k = r.get("sku") or r.get("asin")
        avail = m.num(r.get("fba_available"))
        if avail is None:
            continue  # 整列空/单元格空不当 0 算（否则会把缺数据报成"0 天急"）
        dos = m.days_of_supply(avail, units.get(k, 0.0), W)
        if dos is None:
            continue
        if dos < T["low_stock_ratio_vs_28d"]:
            rows.append((dos, k, r.get("asin"), avail, units.get(k, 0.0)))
    # 供 HTML 明细用的完整字段（店铺/商品/在途）
    detail = {}
    for r in inv:
        k = r.get("sku") or r.get("asin")
        detail[k] = {"shop": r.get("shop") or "", "product": (r.get("product_name") or "").strip(),
                     "inbound": m.num(r.get("fba_inbound"))}

    zero_sales = []
    for r in inv:
        k = r.get("sku") or r.get("asin")
        avail = m.num(r.get("fba_available"))
        if avail is not None and units.get(k, 0.0) <= 0:
            zero_sales.append((k, r.get("asin"), avail, detail.get(k) or {}))

    if degraded:
        detail = "、".join("%s（缺：%s）" % (t, "、".join(q["missing"]) or "关键字段") for t, q in degraded)
        print("【数据质量】%s 上次导入标记 degraded：以下清单只当库存观察，不作为补货建议依据。" % detail)

    if window_days != 28:
        print("【口径提示】销量表实际覆盖 %d 天（不是 28 天），已按实际跨度折算日均。" % window_days)

    rows.sort()
    try:
        hp = render_html(rows, detail, window_days, degraded, zero_sales)
        if hp:
            print("\n✓ HTML 断货预警 → %s" % hp)
    except Exception as e:
        print("\n[warn] HTML 断货预警生成失败：%s" % e, file=sys.stderr)
    if not rows:
        print("【结论】没有 SKU 低于 28 天运营候选预警线。")
        return 0

    crit = [r for r in rows if r[0] < T["days_of_supply_critical"]]
    warn = [r for r in rows if T["days_of_supply_critical"] <= r[0] < T["days_of_supply_alert"]]
    slow = [r for r in rows if r[0] >= T["days_of_supply_alert"]]

    print("【结论】%d 个 SKU 需处理：急件 %d，关注 %d，余下 %d 在候选预警线内（急件不等于采购任务数）。"
          % (len(rows), len(crit), len(warn), len(slow)))
    print("【业务分流】已断货 %d；在库将断货 %d；无近 %d 天销量（新品/停售待确认）%d。"
          % (sum(1 for r in crit if r[3] <= 0), sum(1 for r in crit if r[3] > 0), W, len(zero_sales)))
    for label, group in (("急（<%d 天）" % T["days_of_supply_critical"], crit),
                         ("关注（<%d 天）" % T["days_of_supply_alert"], warn),
                         ("候选预警线内（%d–%d 天）" % (T["days_of_supply_alert"], T["low_stock_ratio_vs_28d"]), slow)):
        if not group:
            continue
        print("\n%s" % label)
        for dos, sku, asin, avail, u28 in group[:15]:
            print("  - %s 可售 %.1f 天（库存 %d，近 28 天销量 %d）" % (sku, dos, avail, u28))

    print("\n【说明】")
    print("  - 口径：只算 FBA 可售（fba_available）÷ 日均销量（按表内实际跨度折算）；")
    print("    在途 fba_inbound 不算可售，本地仓/第三方仓不在这张表里——实际可用可能更多，也可能更紧。")
    print("  - 28 天是我们自己的运营候选预警线（占位未校准）：经验上低库存期自然排名波动、CPC 可能上升，")
    print("    但这是卖家社区观察，不是亚马逊官方规则，不得当因果结论引用。")
    print("  - 官方低库存费是另一回事：长期（约90天）与短期（约30天）历史供货天数双口径均低于 28 天才可能触发")
    print("    资格（2024-04-01 起），以官方页为准 sellercentral.amazon.com/help/hub/reference/external/GV43F6S76Y9DHYRH；")
    print("    本脚本只算单日口径，不能判定低库存费资格。")
    if degraded:
        print("  - 补货建议已降级为观察：先按 scripts/import_lingxing.py 重导补齐关键字段，再谈下单量与交期。")
    else:
        print("  - 补货建议只到\"该补多少天\"这一层，具体下单量与交期要人工确认。")
    # 全仓统一退出码：0=无急档；1=有急档要人看（报告照常归档）；2=数据缺失
    return 1 if crit else 0


def render_html(rows, detail, window_days, degraded, zero_sales=None):
    """SKU 级断货预警 HTML：分档 KPI + 可售天数条形图 + 全量 SKU 补货明细表。"""
    import chartlets as c
    import html_report as hr
    from pathlib import Path

    crit = [r for r in rows if r[0] < T["days_of_supply_critical"]]
    warn = [r for r in rows if T["days_of_supply_critical"] <= r[0] < T["days_of_supply_alert"]]
    slow = [r for r in rows if r[0] >= T["days_of_supply_alert"]]

    def _level(dos):
        if dos < T["days_of_supply_critical"]:
            return "急"
        if dos < T["days_of_supply_alert"]:
            return "关注"
        return "候选"

    def _advice(dos, avail):
        if avail <= 0:
            return '<b style="color:#dc2626">已断货：核在途/交期</b>'
        if dos < T["days_of_supply_critical"]:
            return '<b style="color:#dc2626">在库将断货：核提前期</b>'
        if dos < T["days_of_supply_alert"]:
            return '<span style="color:#d97706">本周安排补货</span>'
        return "观察排产"

    cards = [
        {"label": "急件（<%d天）" % T["days_of_supply_critical"], "value": str(len(crit)), "note": "先分业务状态"},
        {"label": "关注（%d–%d天）" % (T["days_of_supply_critical"], T["days_of_supply_alert"]), "value": str(len(warn)), "note": "本周补货"},
        {"label": "候选（%d–%d天）" % (T["days_of_supply_alert"], T["low_stock_ratio_vs_28d"]), "value": str(len(slow)), "note": "观察排产"},
        {"label": "预警 SKU 合计", "value": str(len(rows)), "note": "口径见页脚"},
    ]

    chart_rows = [{
        "label": (r[1] or "")[:18], "value": round(r[0], 1),
        "color": c.RED if r[0] < T["days_of_supply_critical"] else
                 (c.AMBER if r[0] < T["days_of_supply_alert"] else c.BLUE),
    } for r in rows[:20]]

    table_rows = []
    for dos, sku, asin, avail, u28 in rows:
        d = detail.get(sku) or {}
        table_rows.append([
            sku, hr.linkify_asin(asin) if asin else "", d.get("shop") or "", (d.get("product") or "")[:30],
            "{:,.0f}".format(avail),
            "—" if d.get("inbound") is None else "{:,.0f}".format(d["inbound"]),
            "{:,.0f}".format(u28), "%.2f" % (u28 / float(W)),
            ('<b style="color:#dc2626">%.1f</b>' % dos) if dos < T["days_of_supply_critical"] else "%.1f" % dos,
            m.stock_business_state(avail, u28), _level(dos), _advice(dos, avail),
        ])

    body = (
        hr.banner("断货预警：急 %d · 关注 %d · 候选 %d（SKU 级；急件不等于采购任务数）"
                  % (len(crit), len(warn), len(slow)),
                  "bad" if crit else ("warn" if warn else "good"))
        + c.kpi_cards(cards)
        + (hr.section("可售天数最短的 20 个 SKU（天）",
                      c.hbar_chart(chart_rows, title="可售天数（越短越急）", unit=" 天")) if rows else "")
        + hr.section("SKU 补货明细（%d 个）" % len(rows),
                     hr.table_filterable(
                         hr.table(["SKU 编码", "ASIN", "店铺", "商品", "FBA可售", "在途",
                                   "近%d天销量" % W, "日均", "可售天数", "业务状态", "档位", "建议"],
                                  table_rows, align_right={4, 5, 6, 7, 8}),
                         "stockout-sku") if rows else "<p>没有 SKU 低于 28 天运营候选预警线。</p>")
    )
    if zero_sales:
        zs_rows = [[sku, hr.linkify_asin(asin) if asin else "", (d.get("shop") or ""),
                    "{:,.0f}".format(avail), "新品/停售待确认", "人工核对；不自动生成采购任务"]
                   for sku, asin, avail, d in sorted(zero_sales, key=lambda x: x[2], reverse=True)]
        body += hr.section("无近%d天销量：新品/停售待确认（%d 个）" % (W, len(zero_sales)),
                           "<p>这些 SKU 不进入可售天数分档；没有足够证据区分新品、停售或低动销，不直接下补货结论。</p>"
                           + hr.table(["SKU 编码", "ASIN", "店铺", "FBA可售", "状态", "处理"], zs_rows,
                                      align_right={3}))
    body += hr.methodology([
        ("业务分流", "有销量且 FBA 可售=0：已断货；有销量且可售>0、低于急件线：在库将断货；无窗口销量：新品/停售待确认，不自动生成采购任务"),
        ("可售天数", "FBA 可售（fba_available）÷ 近 28 天等效日均销量；日均 = 销量表总销量 × 28 ÷ 表内实际天数跨度"),
        ("分档阈值", "急 &lt;%s 天（当天补货/转 FBM/停广告止损）；关注 %s–%s 天（核对在途走补货流程）；候选 %s–%s 天（进本周补货计划）" % (T["days_of_supply_critical"], T["days_of_supply_critical"], T["days_of_supply_alert"], T["days_of_supply_alert"], T["low_stock_ratio_vs_28d"])),
        ("不含项", "在途 fba_inbound 不计入可售；本地仓/第三方仓不在表内——实际可用可能更多也可能更紧"),
        ("28 天预警线性质", "运营经验候选线（占位未校准），不是亚马逊官方低库存费判定；官方需长期约 90 天+短期约 30 天历史供货天数双口径"),
        ("防误报", "空库存单元格不当 0；导入标记 degraded 时只作库存观察，不作补货建议依据"),
        ("补货建议", "只到「该补多少天」这一层；具体下单量与交期必须人工确认"),
    ])
    footer = ("口径：可售天数=FBA可售÷日均销量（销量表实际覆盖 %s 天折算成近28天等效）；"
              "在途不计可售；28 天为自设运营候选预警线（未校准），非亚马逊官方规则；"
              "低库存费资格需官方长短期双口径，本报告不判定。%s"
              % (window_days, "部分表导入标记 degraded，清单仅作观察。" if degraded else ""))
    html = hr.render(title="库存断货预警（SKU 级）", subtitle="急件优先 · 补货建议到天",
                     meta="按库存表最新快照生成", banner_html="", body_html=body, footer=footer)
    inv_day = ""
    try:
        inv_day = m.table_dates(m.load("inventory_daily"))[-1]
    except Exception:
        pass
    import datetime as _dt
    out = Path(__file__).resolve().parents[3] / "data" / "reports" / "stockout" / (
        "%s_stockout.html" % (inv_day or _dt.date.today().isoformat()))
    return hr.save(html, out)


if __name__ == "__main__":
    sys.exit(main())
