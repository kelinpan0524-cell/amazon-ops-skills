#!/usr/bin/env python3
"""管理层经营总览（一页纸 HTML）：各店铺组汇总，5 秒看懂。

用法：python3 skills/amz-company-overview/scripts/run.py
输出：data/reports/mgmt/<日期>_overview.html
口径：shop_daily.csv · USD · 下单口径 · 跨店相加；不展示利润（未校准红线）。
"""
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
OUT_DIR = ROOT / "data" / "reports" / "mgmt"
WINDOW_DAYS = 30


# 数值读取与「最新完整日」统一走共享层（各店允许不同步）
val = sd.val
ratio = sd.ratio


def profit_summary(day=None):
    """当天毛利汇总。**只统计有采购成本的行**（has_cost=1）。

    口径：领星利润报表，gross_profit 已扣采购成本+FBA配送费+佣金，
    但**不含头程物流**（实测 proportion_of_cg_transport 恒为 0），所以是上限值。
    没录采购成本的 ASIN 不算进来——把"没录"当"成本 0"会把毛利率算高。
    """
    rows = m.load("profit_daily")
    if not rows:
        return None
    with_cost = [r for r in rows if (m.num(r.get("has_cost")) or 0) > 0]
    if not with_cost:
        return None
    ds = sorted({m.row_date(r) for r in with_cost if m.row_date(r)})
    if not ds:
        return None
    use = day if (day and day in ds) else ds[-1]
    cur = [r for r in with_cost if m.row_date(r) == use]
    rev = sum((m.num(r.get("revenue")) or 0) for r in cur)
    gp = sum((m.num(r.get("gross_profit")) or 0) for r in cur)
    total_rows = [r for r in rows if m.row_date(r) == use]
    neg = sum(1 for r in cur if (m.num(r.get("gross_profit")) or 0) < 0)
    return {"date": use, "rev": rev, "gp": gp,
            "margin": (gp / rev) if rev else None,
            "n_cost": len(cur), "n_all": len(total_rows), "n_neg": neg}


def latest_full_rows(rows_by_date, today):
    """{date: {shop: row}} → {shop: (date, row)}：各店取各自最近完整日。

    输入是按日期组织的视图（本技能的趋势图要用），共享层按「按店铺组织」处理，
    这里先转置再交给 sd.latest_by_shop，避免两边各写一套"跳过今天"的逻辑。
    """
    by_shop = {}
    for d, shop_rows in rows_by_date.items():
        for shop, row in shop_rows.items():
            by_shop.setdefault(shop, {})[d] = row
    return sd.latest_by_shop(by_shop, today)


def shops_display(shop):
    try:
        cfg = json.loads(SHOPS_JSON.read_text(encoding="utf-8"))["shops"]
        return (cfg.get(shop) or {}).get("display", shop)
    except (OSError, json.JSONDecodeError, KeyError):
        return shop


def shop_subtitle():
    """总览副标题完全来自本机店铺配置，公开源码不携带真实店铺名。"""
    try:
        shops = json.loads(SHOPS_JSON.read_text(encoding="utf-8"))["shops"]
        return " · ".join((cfg or {}).get("display", key) for key, cfg in shops.items())
    except (OSError, json.JSONDecodeError, KeyError, TypeError):
        return "店铺组经营总览"


def profit_html(prof):
    """毛利明细：按店拆 + 亏损 SKU 提示。只统计有成本的。"""
    rows = m.load("profit_daily")
    with_cost = [r for r in rows
                 if (m.num(r.get("has_cost")) or 0) > 0
                 and m.row_date(r) == prof["date"]]
    by = {}
    for r in with_cost:
        b = by.setdefault(r.get("shop") or "?", {"rev": 0.0, "gp": 0.0, "n": 0, "neg": 0})
        b["rev"] += m.num(r.get("revenue")) or 0
        gp = m.num(r.get("gross_profit")) or 0
        b["gp"] += gp
        b["n"] += 1
        if gp < 0:
            b["neg"] += 1
    trs = []
    for shop, b in sorted(by.items(), key=lambda kv: -kv[1]["rev"]):
        mg = (b["gp"] / b["rev"] * 100) if b["rev"] else None
        # 状态不能只看整店毛利率：示例整店 31.8% 看着正常，但里面有 5 个 ASIN
        # 在亏（2026-11-04 实测）。整店加权平均会把亏损的品盖掉。
        badge = "—"
        if mg is not None:
            if mg < 0:
                badge = '<span class="tag bad">整店亏损</span>'
            elif mg < 15:
                badge = '<span class="tag warn">偏低</span>'
            elif b["neg"] > 0:
                badge = '<span class="tag warn">%d 个亏损</span>' % b["neg"]
            else:
                badge = '<span class="tag good">正常</span>'
        trs.append([shops_display(shop), str(b["n"]), "$%s" % c._fmt(round(b["rev"])),
                    "$%s" % c._fmt(round(b["gp"])),
                    ("%.1f%%" % mg) if mg is not None else "-",
                    str(b["neg"]) if b["neg"] else "0", badge])
    note = ('<p style="font-size:11.5px;color:#6b7280;margin-top:8px;line-height:1.75">'
            '<b>只统计录了采购成本的 ASIN</b>（%d/%d 个）——没录的不算进来，'
            '否则会把"没录"当成"成本 0"，毛利率虚高。<br>'
            '领星口径已扣采购成本 + FBA 配送费 + 佣金，<b>但不含头程物流</b>'
            '（实测头程占比恒为 0），所以这是<b>上限值</b>，真实毛利要再低一些。<br>'
            '阈值：&lt;15%% 偏低、&lt;0%% 亏损（config/targets.json 的 profit 段）。'
            % (prof["n_cost"], prof["n_all"]))
    return (hr.table(["店铺", "有成本 ASIN", "销售额", "毛利", "毛利率", "亏损数", "状态"],
                     trs, align_right={1, 2, 3, 4, 5}) + note)


def main():
    shops = json.loads(SHOPS_JSON.read_text(encoding="utf-8"))["shops"]
    rows = m.load("shop_daily")
    if not rows:
        print("没有 shop_daily 数据（先跑 scripts/fetch_lingxing.py）")
        return 2  # 2=数据缺失
    today = dt.date.today().isoformat()

    rows_by_date = {}
    for r in rows:
        d = m.row_date(r)
        if d:
            rows_by_date.setdefault(d, {})[r.get("shop")] = r
    picked = latest_full_rows(rows_by_date, today)
    if not picked:
        print("没有非今天的完整日数据（领星当日未产齐；明天再跑或手工指定窗口）")
        return 2
    as_of = max(d for d, _ in picked.values())

    # ---- 全公司汇总（各店最新完整日之和；环比=与各自前一日之和比）----
    tot = {k: sum((val(r, k) or 0) for _, r in picked.values()) for k in
           ("units", "revenue", "spend", "fba_available")}
    # 前一日必须按「日期」排序取最近的那一行。
    # 原先写成遍历 rows_by_date 的字典顺序再取 [-1]，而字典顺序来自 CSV 行序——
    # 补历史数据时 CSV 会变成乱序（fetch_lingxing 是"旧行 + 新行"追加），
    # 于是会取到更早的日期当"前一日"，环比与异常判定静默算错（2026-11-04 审计发现）。
    prev_vals = {}
    for shop, (d, _r) in picked.items():
        earlier_dates = sorted(dd for dd, shop_rows in rows_by_date.items()
                               if shop in shop_rows and dd < d)
        if earlier_dates:
            prev_vals[shop] = rows_by_date[earlier_dates[-1]][shop]
    prev_tot = {k: sum((val(r, k) or 0) for r in prev_vals.values()) for k in tot}

    def ratio(cur, old):
        return (cur - old) / old if old else None

    tacos = tot["spend"] / tot["revenue"] if tot["revenue"] else None
    cards = [
        {"label": "销售额(USD)", "value": "$%s" % c._fmt(tot["revenue"]),
         "delta": ratio(tot["revenue"], prev_tot["revenue"])},
        {"label": "销量(件)", "value": c._fmt(tot["units"]),
         "delta": ratio(tot["units"], prev_tot["units"])},
        {"label": "广告花费", "value": "$%s" % c._fmt(tot["spend"]),
         "delta": ratio(tot["spend"], prev_tot["spend"]), "delta_good": False},
        {"label": "TACOS", "value": ("%s%%" % c._fmt(tacos * 100)) if tacos is not None else "缺数据",
         "note": bm.kpi_note("tacos", None, bm.history_baseline()),
         "delta_good": False},
        {"label": "FBA 可售(件)", "value": c._fmt(tot["fba_available"]),
         "note": "多店合计·仅 FBA"},
    ]
    prof = profit_summary(as_of)
    if prof and prof["margin"] is not None:
        # 只算录了采购成本的那部分，覆盖率写在 note 里——不然读的人不知道分母是谁
        cards.append({
            "label": "毛利率",
            "value": "%.1f%%" % (prof["margin"] * 100),
            "note": "%d/%d 个 ASIN 有成本 · 不含头程" % (prof["n_cost"], prof["n_all"])})

    # ---- 店铺对比 ----
    hbars = []
    for shop, (d, r) in sorted(picked.items(), key=lambda kv: -(val(kv[1][1], "revenue") or 0)):
        rev = val(r, "revenue") or 0
        prev_r = prev_vals.get(shop)
        prev_rev = (val(prev_r, "revenue") or 0) if prev_r else None
        dlt = ratio(rev, prev_rev) if prev_rev else None
        note = ("环比%+.0f%%" % (dlt * 100)) if dlt is not None else "首日"
        color = c.GREEN if (dlt or 0) >= 0 else c.RED
        hbars.append({"label": shops[shop]["display"], "value": rev,
                      "note": note, "color": color})
    donut_parts = [{"label": shops[s]["display"], "value": val(r, "revenue") or 0}
                   for s, (_, r) in picked.items()]

    # ---- 各店趋势（近 30 天小图）----
    trend_html = ""
    cutoff = (dt.date.fromisoformat(as_of) - dt.timedelta(days=WINDOW_DAYS)).isoformat()
    for shop in shops:
        pts = [(d, rows_by_date[d][shop]) for d in sorted(rows_by_date)
               if shop in rows_by_date[d] and cutoff <= d <= as_of]
        labels = [d[5:] for d, _ in pts]
        trend_html += c.line_chart(
            labels, [{"name": shops[shop]["display"],
                      "values": [val(r, "revenue") for _, r in pts],
                      "color": c.PALETTE[list(shops).index(shop) % len(c.PALETTE)]}],
            w=460, h=200, title="%s 销售额（USD）" % shops[shop]["display"], y_fmt="money")

    # ---- 异常摘要 ----
    alerts = []
    for shop, (d, r) in picked.items():
        prev_r = prev_vals.get(shop)
        if not prev_r:
            continue
        rev, prev_rev = val(r, "revenue") or 0, val(prev_r, "revenue") or 0
        if prev_rev and (rev - prev_rev) / prev_rev <= -0.2:
            alerts.append('<li><span class="tag bad">下滑</span> %s %s 销售额环比 %+.0f%%（%s → %s）——先查差评/排名/竞对降价</li>'
                          % (shops[shop]["display"], d, (rev - prev_rev) / prev_rev * 100,
                             "$%s" % c._fmt(prev_rev), "$%s" % c._fmt(rev)))
        acos_v = val(r, "acos")
        if acos_v is not None and acos_v > 0.30:
            alerts.append('<li><span class="tag warn">广告</span> %s ACOS %.0f%% 偏高（成本未校准，仅看绝对值）</li>'
                          % (shops[shop]["display"], acos_v * 100))
        fb = val(r, "fba_available")
        u = val(r, "units")
        if fb is not None and u:
            dos = fb / u
            if dos < 14:
                alerts.append('<li><span class="tag warn">库存</span> %s FBA 可售约 %.0f 天（粗口径：可售÷当日销量，仅 FBA）</li>'
                              % (shops[shop]["display"], dos))
    alerts_html = "".join(alerts) or '<li><span class="tag good">正常</span> 各店无异动</li>'

    rev_d = ratio(tot["revenue"], prev_tot["revenue"])
    if rev_d is None:
        banner_txt, level = "多店总览（数据截至 %s）：首期无环比基线" % as_of, "warn"
    elif rev_d >= 0.1:
        banner_txt, level = "多店合计销售额环比 %+.0f%%，上行（截至 %s）" % (rev_d * 100, as_of), "good"
    elif rev_d <= -0.1:
        banner_txt, level = "多店合计销售额环比 %+.0f%%，注意下滑归因（截至 %s）" % (rev_d * 100, as_of), "bad"
    else:
        banner_txt, level = "多店合计销售额环比 %+.0f%%，平稳（截至 %s）" % (rev_d * 100, as_of), "good"

    # ---- 各店当月目标进度（月目标 vs 当月累计；按「达成 ÷ 时间进度」判掉队）----
    # 为什么不直接看达成率：月初时间才过 20%，达成率当然低，那不是落后。
    mon = as_of[:7]
    prog_rows, prog_total = [], {"mtd": 0.0, "tgt": 0.0}
    for shop in shops:
        mtd = sum((val(r, "revenue") or 0) for r in rows
                  if r.get("shop") == shop and (m.row_date(r) or "")[:7] == mon)
        pr = bm.month_progress_ratio(shop, mtd, as_of)
        if not pr:
            continue
        prog_total["mtd"] += pr["mtd"]
        prog_total["tgt"] += pr["target_usd"]
        if pr["tprog"] < 0.15:
            state, tag = "月初，还看不出", "warn"
        elif pr["ratio"] >= 1.0:
            state, tag = "按进度领先", "good"
        elif pr["ratio"] >= 0.8:
            state, tag = "基本跟上", "good"
        elif pr["ratio"] >= 0.6:
            state, tag = "落后进度", "warn"
        else:
            state, tag = "严重落后", "bad"
        prog_rows.append([
            shops[shop].get("display", shop),
            "$%s" % c._fmt(round(pr["mtd"])),
            "$%s" % c._fmt(round(pr["target_usd"])),
            "%.1f%%" % (pr["pct"] * 100),
            "%.0f%%" % (pr["tprog"] * 100),
            '<span class="tag %s">%s</span>' % (tag, state),
        ])
    if prog_rows and prog_total["tgt"]:
        tp = prog_total["mtd"] / prog_total["tgt"]
        prog_rows.append(["<b>多店合计</b>", "$%s" % c._fmt(round(prog_total["mtd"])),
                          "$%s" % c._fmt(round(prog_total["tgt"])),
                          "<b>%.1f%%</b>" % (tp * 100), "—", ""])
        shop_prog_html = (
            hr.table(["店铺", "当月已卖", "月目标", "达成", "时间已过", "状态"],
                     prog_rows, align_right={1, 2, 3, 4})
            + '<p style="font-size:11.5px;color:#6b7280;margin-top:6px;line-height:1.7">'
              '状态按 <b>达成 ÷ 时间进度</b> 判：≥100% 领先、80-100% 跟上、60-80% 落后、&lt;60% 严重落后。'
              '月初（时间进度 &lt;15%）不判。月目标见 <code>config/targets.json</code>，'
              '是按各店近 12 个月销售占比拆出来的估算口径，不是逐店下达的指标。</p>')
    else:
        shop_prog_html = "<p>未配置店月目标（<code>config/targets.json</code> 的 shops.&lt;店&gt;.monthly_target_usd）。</p>"

    # ---- 年度目标进度（目标在 config/targets.json，全 USD 口径，不做币种换算）----
    prog = bm.revenue_progress()
    if prog.get("ready"):
        lead = "领先" if prog["on_track"] else "落后"
        delta_pp = (prog["pct"] - prog["time_pct"]) * 100
        if prog["months_left"]:
            tail = ("剩余 %d 个月，月均需 $%s 才能达标"
                    % (prog["months_left"], c._fmt(round(prog["need_per_month_usd"]))))
        else:
            tail = "年度已结束"
        progress_html = hr.progress(
            prog["actual_usd"], prog["target_usd"], prog["time_pct"],
            foot=("达成 %.1f%% · 时间进度 %.1f%% · <b>%s %.1f 个点</b> · %s"
                  % (prog["pct"] * 100, prog["time_pct"] * 100, lead, abs(delta_pp), tail)))
    else:
        progress_html = ("<p>年度销售目标未设定（<code>config/targets.json</code> 的 "
                         "annual_revenue_target_usd）。</p>")

    # SKU 层：当日销售额 Top 榜 + 库存急件（总览也要能落到具体 ASIN/SKU）
    import sku_table as st
    sku_rows, sku_day = st.sku_daily_rows()
    top_sku = [s for s in sku_rows if s["revenue"] > 0][:30]
    urgent_sku = [s for s in sku_rows if s.get("dos") is not None and s["dos"] < 10]
    sku_html = ""
    if top_sku:
        sku_html += hr.section("当日 SKU 销售额 Top %d（%s）" % (len(top_sku), sku_day),
                               st.sku_table(top_sku, table_id="ov-top-sku"))
    sku_html += hr.section("库存急件 SKU（可售 < 10 天 · %d 个）" % len(urgent_sku),
                           st.sku_table(urgent_sku, table_id="ov-urgent-sku") if urgent_sku
                           else "<p>无。</p>")

    target_heading = ("%s 年度销售目标（目标 $%s）" % (
        prog.get("year", ""), c._fmt(round(prog["target_usd"])))) if prog.get("ready") else "年度销售目标（未设定）"
    body = (
        hr.banner(banner_txt, level)
        + c.kpi_cards(cards)
        + hr.section(target_heading, progress_html)
        + hr.section("毛利情况（%s）" % (prof["date"] if prof else as_of),
                     profit_html(prof) if prof else
                     "<p>没有 profit_daily 数据（先跑 scripts/fetch_profit.py --days 7）。</p>")
        + hr.section("各店 %s 月度目标进度" % mon, shop_prog_html)
        + hr.section("店铺对比（各自最新完整日）",
                     c.hbar_chart(hbars, title="销售额对比（USD）")
                     + '<div style="display:flex;gap:12px;flex-wrap:wrap;align-items:center">'
                     + c.donut(donut_parts, w=300, h=250, title="销售额占比")
                     + '<div style="flex:1;min-width:280px"><ul class="plain">%s</ul></div></div>'
                     % alerts_html)
        + hr.section("各店近 %d 天趋势" % WINDOW_DAYS,
                     '<div style="display:flex;flex-wrap:wrap;gap:12px">%s</div>' % trend_html)
        + sku_html
    )
    body += hr.methodology([
        ("金额口径", "全部 <b>USD（美金）</b>，领星折算返回，不做币种换算；目标 config/targets.json 同为 USD"),
        ("汇总口径", "各店取各自最近完整日（当日数据领星未产齐则回退）；销售额为产品表现 total_sum、下单口径，跨店相加"),
        ("月度达成率", "当月累计销售额 ÷ 店月目标；进度比 = 达成率 ÷ 时间进度（当月已过天数 ÷ 当月天数）；&lt;0.8 落后、&lt;0.6 严重落后"),
        ("年度进度", "实际累计（shop_monthly）÷ 年目标；时间进度 = 已过月份 ÷ 12；剩余月均需 =（年目标 − 已达成）÷ 剩余月数"),
        ("当日 SKU 销售额榜", "按当日 SKU 销售额降序取 Top 30（多店合并），含销量/广告/ACOS/可售天数"),
        ("库存急件榜", "可售天数 = FBA 可售 ÷ 近 28 天等效日均销量，&lt;10 天为急件"),
        ("不展示项", "毛利/利润未校准不展示；库存仅 FBA 可售"),
    ])
    footer = ("口径：领星产品表现 total_sum · USD · 下单口径 · 跨店相加；毛利/利润未校准不展示；"
              "各店取各自最近完整日（今日数据领星未产齐）；库存仅 FBA 可售。数据源 shop_daily.csv。")
    html = hr.render(
        title="多店经营总览", subtitle=shop_subtitle(),
        meta="报告日 %s · 数据截至 %s" % (today, as_of),
        banner_html="", body_html=body, footer=footer)
    out = hr.save(html, OUT_DIR / ("%s_overview.html" % as_of))
    print("✓ 多店总览 → %s" % out)


if __name__ == "__main__":
    main()
