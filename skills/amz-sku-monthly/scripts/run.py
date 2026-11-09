#!/usr/bin/env python3
"""月度经营复盘：看结构，不看单条。月度只看四件事——卖什么、怎么赚、压在哪儿、广告占比。"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "_shared"))
import metrics as m  # noqa: E402


def main():
    sales_all = m.load("sales_daily")
    ads_all = m.load("ads_daily")
    inv_all = m.load("inventory_daily")
    if not sales_all:
        print("【数据情况】没有销量表，复盘做不了。先导领星产品表现报表。")
        return

    # 月度窗口：默认复盘「表内最新日期所在月」，--month 2026-10 可指定（写在环境变量 AMZ_MONTH）
    import os
    dates = m.table_dates(sales_all)
    month = os.environ.get("AMZ_MONTH") or (dates[-1][:7] if dates else None)
    if not month:
        print("【数据情况】销量表里没有可识别的日期，复盘做不了。")
        return
    sales = m.rows_in_month(sales_all, month)
    ads = m.rows_in_month(ads_all, month)
    inv = inv_all  # 库存是时点值，取最新快照即可
    if not sales:
        print("【数据情况】%s 没有销量数据（表覆盖 %s~%s）。" %
              (month, dates[0] if dates else "?", dates[-1] if dates else "?"))
        return
    prev_month_sales = []
    if dates:
        y, mo = int(month[:4]), int(month[5:7])
        pm = "%04d-%02d" % ((y, mo - 1) if mo > 1 else (y - 1, 12))
        prev_month_sales = m.rows_in_month(sales_all, pm)

    by_sku, revenue, units, sessions = {}, 0.0, 0.0, 0.0
    for r in sales:
        k = r.get("sku") or r.get("asin") or "?"
        d = by_sku.setdefault(k, {"units": 0.0, "revenue": 0.0, "sessions": 0.0})
        d["units"] += m._f(r.get("units"))
        d["revenue"] += m._f(r.get("revenue"))
        d["sessions"] += m._f(r.get("sessions"))
        revenue += m._f(r.get("revenue"))
        units += m._f(r.get("units"))
        sessions += m._f(r.get("sessions"))

    print("【卖什么】（%s 口径：只汇总该月数据）" % month)
    print("  总销量 %d 件，销售额 %.2f，会话 %d，整体转化率 %s"
          % (units, revenue, sessions,
             "缺数据" if m.cvr(units, sessions) is None else "%.2f%%" % (m.cvr(units, sessions) * 100)))
    if prev_month_sales:
        prev_rev = sum(m._f(r.get("revenue")) for r in prev_month_sales)
        prev_units = sum(m._f(r.get("units")) for r in prev_month_sales)
        if prev_rev > 0:
            print("  环比上月：销售额 %+.1f%%（上月 %.2f），销量 %+.1f%%（上月 %d 件）"
                  % ((revenue - prev_rev) / prev_rev * 100, prev_rev,
                     (units - prev_units) / prev_units * 100 if prev_units else 0.0, prev_units))
    top = sorted(by_sku.items(), key=lambda kv: kv[1]["revenue"], reverse=True)[:5]
    for k, v in top:
        share = v["revenue"] / revenue * 100 if revenue else 0
        print("  - %s：销售额 %.2f（占 %.0f%%），%d 件" % (k, v["revenue"], share, v["units"]))
    if len(by_sku) > 5:
        rest = revenue - sum(v["revenue"] for _, v in top)
        print("  - 其余 %d 个 SKU 合计 %.2f（占 %.0f%%）——长尾是否值得留，看退货与广告花费"
              % (len(by_sku) - 5, rest, rest / revenue * 100 if revenue else 0))

    print("\n【怎么赚】")
    if ads:
        spend = sum(m._f(r.get("spend")) for r in ads)
        ad_sales = sum(m._f(r.get("sales")) for r in ads)
        ratio = spend / revenue * 100 if revenue else None
        print("  广告花费 %.2f，广告销售额 %.2f，ACOS %s，广告花费占销售额 %s"
              % (spend, ad_sales,
                 "无广告销售" if m.acos(spend, ad_sales) is None else "%.1f%%" % (m.acos(spend, ad_sales) * 100),
                 "缺数据" if ratio is None else "%.1f%%" % ratio))
        print("  注：没有成本结构时算不出真实毛利，这一项只能看趋势，不能下\"赚不赚钱\"的结论。")
    else:
        print("  没有广告表，跳过。")

    print("\n【压在哪儿】")
    if not inv:
        print("  没有库存表，跳过。")
    else:
        avail_rows = [r for r in inv if m.num(r.get("fba_available")) is not None]  # 空单元格不计 0
        zero = sum(1 for r in avail_rows if m.num(r.get("fba_available")) <= 0)
        total_units = sum(m.num(r.get("fba_available")) for r in avail_rows)
        skipped = len(inv) - len(avail_rows)
        tail = "，另有 %d 行库存值为空未计入" % skipped if skipped else ""
        print("  FBA 在库 SKU %d 个，可售库存合计 %d 件，其中 %d 个 SKU 可售为 0%s"
              "（仅 fba_available 口径：在途 fba_inbound 与本地仓不在内）"
              % (len(inv), total_units, zero, tail))
        slow = [(r.get("sku") or r.get("asin")) for r in avail_rows
                if m.num(r.get("fba_available")) > 0
                and by_sku.get(r.get("sku") or r.get("asin"), {}).get("units", 0) <= 0]
        if slow:
            print("  有库存但本月 0 销的 SKU %d 个，示例：%s" % (len(slow), "、".join(slow[:8])))

    degraded = m.degraded_tables(["sales_daily", "ads_daily", "inventory_daily"])
    print("\n【本月的结论去哪】")
    if degraded:
        detail = "、".join("%s（缺：%s）" % (t, "、".join(q["missing"]) or "关键字段") for t, q in degraded)
        print("  【数据质量】%s 上次导入标记 degraded：本月只出结构观察，不写结论性判断。" % detail)
        print("  先按 scripts/import_lingxing.py 重导补齐关键字段，再复盘定调。")
    else:
        print("  三条以内写进 judgements/<日期>-monthly.md，标明预期与复核日；")
        print("  连续三个月被证实的结论，升级为 profiles/company.md 的事实。")


if __name__ == "__main__":
    main()
