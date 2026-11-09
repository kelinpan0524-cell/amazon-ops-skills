#!/usr/bin/env python3
"""周/月经营复盘：本期 vs 上期（环比）+ vs 去年（同比）+ 各店贡献 + 注意事项。

用法：
  python3 skills/amz-week-month-review/scripts/run.py --period week
  python3 skills/amz-week-month-review/scripts/run.py --period month --anchor 2026-10

数据源：周报读 shop_daily（日粒度）、月报读 shop_monthly（月粒度，24 个月历史才能算同比）。
口径：USD、下单口径；金额整数显示；不展示利润（未校准红线）。
同比历史不足时明确写 needs_data，不估算。
"""
import argparse
import datetime as dt
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent.parent / "_shared"))
import chartlets as c    # noqa: E402
import html_report as hr  # noqa: E402
import metrics as m      # noqa: E402
import shopdata as sd    # noqa: E402
import benchmarks as bm  # noqa: E402  （年度目标进度）  （共享读取层：口径与时间边界唯一一份）

ROOT = HERE.parent.parent.parent
SHOPS_JSON = ROOT / "config" / "shops.json"
OUT_DIR = ROOT / "data" / "reports" / "period"
TREND_PERIODS = 12


# 时间边界与环比统一由 shopdata 提供（去年同期按 ISO 周对齐，不是简单减天数）
week_bounds = sd.week_bounds
month_bounds = sd.month_bounds
ratio = sd.ratio


def load_index(period="week"):
    """按周期选表：周报读日表（shop_daily），月报读月表（shop_monthly）。

    为什么分开：日表只有最近的日粒度数（几周~几个月），月表有 24 个月历史。
    月报要算同比，必须读月表；周报要算周末尾那段，必须读日表。
    """
    if period == "month":
        idx = {}
        for r in m.load("shop_monthly"):
            mon = str(r.get("month", "")).strip()
            shop = r.get("shop")
            if mon and shop:
                idx.setdefault(shop, {})[mon] = r
        return idx, "month"
    idx = {}
    for r in m.load("shop_daily"):
        d = m.row_date(r)
        shop = r.get("shop")
        if d and shop:
            idx.setdefault(shop, {})[d] = r
    return idx, "day"


def grep_month(idx, month):
    """从月表 idx 里取某月（YYYY-MM）的各店行。"""
    return {shop: by[m] for shop, by in idx.items() if month in by}


def agg(idx, start, end, shops=None, granularity="day"):
    """[start,end] 区间内按店汇总。返回 (per_shop, total, covered_units)。

    granularity="day" 时 idx 的 key 是 YYYY-MM-DD；"month" 时是 YYYY-MM。
    区间边界按粒度截断后再比较（月粒度下 2026-10-01 与 2026-10 不能直接比大小）。
    """
    cut = 7 if granularity == "month" else 10
    lo, hi = start.isoformat()[:cut], end.isoformat()[:cut]
    out = {}
    unit_set = set()
    for shop, by_date in idx.items():
        if shops and shop not in shops:
            continue
        acc = {"units": 0.0, "revenue": 0.0, "spend": 0.0, "ad_sales": 0.0,
               "sessions": 0.0, "orders": 0.0}
        hit = False
        for d, r in by_date.items():
            if lo <= d <= hi:
                hit = True
                unit_set.add(d)
                for k in acc:
                    acc[k] += m.num(r.get(k)) or 0.0
        if hit:
            out[shop] = acc
    total = {k: sum(v[k] for v in out.values()) for k in
             ("units", "revenue", "spend", "ad_sales", "sessions", "orders")}
    # 期末库存快照：取区间末尾那个粒度的快照
    total["fba_available"] = sum(
        (m.num(r.get("fba_available")) or 0.0)
        for by_date in idx.values() for d, r in by_date.items()
        if d == hi) or None
    return out, total, len(unit_set)


# ---------------- 归因分析 ----------------
# 复盘只说"跌了 20%"没用，要说"跌在哪儿"。三个层次：
#   1) 哪个店贡献了多少变化（钱的角度）
#   2) 哪个 SKU 贡献了多少变化（品的角度，需要 sales_daily）
#   3) 销量效应 vs 价格效应（量价分解，连环替代法）

def contrib_by_shop(cur_by_shop, prev_by_shop):
    """店铺贡献：每店 ΔRev 及其占总变化的比例。返回 (rows, total_delta)。"""
    total_delta = sum((cur_by_shop.get(s, {}).get("revenue") or 0)
                      - (prev_by_shop.get(s, {}).get("revenue") or 0)
                      for s in set(cur_by_shop) | set(prev_by_shop))
    rows = []
    for shop in set(cur_by_shop) | set(prev_by_shop):
        c = cur_by_shop.get(shop, {}).get("revenue") or 0
        pv = prev_by_shop.get(shop, {}).get("revenue") or 0
        delta = c - pv
        share = (delta / total_delta * 100) if total_delta else None
        rows.append({"shop": shop, "cur": c, "prev": pv, "delta": delta, "share": share})
    rows.sort(key=lambda x: -x["delta"])
    return rows, total_delta


def contrib_by_sku(start, end, prev_start, prev_end):
    """SKU 贡献（读 sales_daily）。窗口没覆盖就返回 None。

    返回 {"rows": [...], "covered": bool, "cur_days": n, "prev_days": n}
    """
    rows = m.load("sales_daily")
    if not rows:
        return None, "没有 sales_daily（SKU 级销量），归因只能到店铺层"

    def window(s, e):
        lo, hi = s.isoformat(), e.isoformat()
        acc = {}
        for r in rows:
            d = m.row_date(r)
            if not d or not (lo <= d <= hi):
                continue
            k = (r.get("shop") or "", r.get("sku") or r.get("asin") or "")
            a = acc.setdefault(k, {"rev": 0.0, "units": 0.0})
            a["rev"] += m.num(r.get("revenue")) or 0
            a["units"] += m.num(r.get("units")) or 0
        return acc

    cur_w, prev_w = window(start, end), window(prev_start, prev_end)
    if not prev_w:
        return None, ("上期没有 SKU 级数据（sales_daily 只有最近几天），"
                      "本期/上期对比只在店铺层做——要 SKU 归因得先把 sales_daily 补到两周以上")
    out = []
    for k in set(cur_w) | set(prev_w):
        c = cur_w.get(k, {}).get("rev", 0.0)
        pv = prev_w.get(k, {}).get("rev", 0.0)
        out.append({"shop": k[0], "sku": k[1], "cur": c, "prev": pv, "delta": c - pv})
    out.sort(key=lambda x: -x["delta"])
    return {"rows": out, "covered": True}, None


def price_volume(q1, rev1, q0, rev0):
    """量价分解（连环替代）：ΔRev = (Q1-Q0)*P0 + (P1-P0)*Q1。

    先算销量变化带来的钱（按上期价格），再算价格变化带来的钱（按本期销量）。
    两项相加等于总变化——这样能说清"是卖得少了还是卖便宜了"。
    """
    if not q0 or not rev0:
        return None
    p0, p1 = rev0 / q0, (rev1 / q1 if q1 else 0)
    vol_eff = (q1 - q0) * p0
    price_eff = (p1 - p0) * q1
    return {"p0": p0, "p1": p1, "q0": q0, "q1": q1,
            "vol_eff": vol_eff, "price_eff": price_eff,
            "delta": rev1 - rev0}


def render_attribution(cur, prev, cur_by_shop, prev_by_shop, s, e, ps, pe, shops_cfg):
    """归因章节 HTML。没数据就明说，不编。"""
    def disp(name):
        return (shops_cfg.get(name) or {}).get("display", name)

    parts = []

    # 1) 量价分解
    pv = price_volume(cur.get("units") or 0, cur.get("revenue") or 0,
                      prev.get("units") or 0, prev.get("revenue") or 0)
    if pv:
        parts.append(
            '<p><b>量价拆解</b>：总变化 <b>$%s</b> = 销量效应 $%s + 价格效应 $%s</p>'
            '<p style="font-size:12px;color:#6b7280">销量 %s → %s 件，'
            '均价 $%.2f → $%.2f。销量效应为正说明<span>卖得多了</span>；'
            '价格效应为负说明<span>卖便宜了</span>。</p>'
            % (c._fmt(round(pv["delta"])), c._fmt(round(pv["vol_eff"])),
               c._fmt(round(pv["price_eff"])),
               c._fmt(pv["q0"]), c._fmt(pv["q1"]), pv["p0"], pv["p1"]))

    # 2) 店铺贡献
    rows, total_delta = contrib_by_shop(cur_by_shop, prev_by_shop)
    if rows:
        trs = []
        for r in rows:
            trs.append([
                disp(r["shop"]), "$%s" % c._fmt(round(r["prev"])), "$%s" % c._fmt(round(r["cur"])),
                ("%+d" % round(r["delta"])).replace("-", "-$").replace("+", "+$")
                if r["delta"] else "0",
                ("%.0f%%" % r["share"]) if r["share"] is not None else "-"])
        parts.append("<p style='margin-top:10px'><b>跌在哪个店</b></p>"
                     + hr.table(["店铺", "上期", "本期", "变化", "占总变化"],
                                trs, align_right={1, 2, 3, 4}))

    # 3) SKU 贡献
    data, why = contrib_by_sku(s, e, ps, pe)
    if data:
        top_up = [x for x in data["rows"] if x["delta"] > 0][:5]
        top_dn = [x for x in reversed(data["rows"]) if x["delta"] < 0][:5]
        if top_dn:
            trs = [[disp(x["shop"]), x["sku"],
                    "$%s" % c._fmt(round(x["prev"])), "$%s" % c._fmt(round(x["cur"])),
                    "-$%s" % c._fmt(round(abs(x["delta"])))] for x in top_dn]
            parts.append("<p style='margin-top:10px'><b>跌得最多的 5 个 SKU</b></p>"
                         + hr.table(["店铺", "SKU", "上期", "本期", "少了"],
                                    trs, align_right={2, 3, 4}))
        if top_up:
            trs = [[disp(x["shop"]), x["sku"],
                    "$%s" % c._fmt(round(x["prev"])), "$%s" % c._fmt(round(x["cur"])),
                    "+$%s" % c._fmt(round(x["delta"]))] for x in top_up]
            parts.append("<p style='margin-top:10px'><b>涨得最多的 5 个 SKU</b></p>"
                         + hr.table(["店铺", "SKU", "上期", "本期", "多了"],
                                    trs, align_right={2, 3, 4}))
    elif why:
        parts.append('<p style="color:#b45309;font-size:12.5px;margin-top:10px">'
                     'SKU 级归因未做：%s</p>' % why)

    parts.append('<p style="font-size:11.5px;color:#6b7280;margin-top:10px;line-height:1.7">'
                 '归因只到「钱从哪个店/哪个 SKU 少了」这一层。'
                 '为什么少（断货/降价/被抢购物车/广告停了）要靠预警和运营判断，'
                 '机器不替人猜。</p>')
    return hr.section("归因分析（变化从哪来）", "".join(parts))



def _iso(d):
    return d.isoformat() if hasattr(d, "isoformat") else str(d)


def detail_sections(s, e, ps, pe):
    """周/月报加深的明细段：SKU 本期 vs 上期、广告烧钱、库存急件、本期新差评。

    长尾款以周/月为主监控口径，这些明细就是周/月会的 Action List。
    """
    s, e, ps, pe = _iso(s), _iso(e), _iso(ps), _iso(pe)
    cur, prev = {}, {}
    for r in m.load("sales_daily"):
        d = m.row_date(r)
        k = r.get("sku") or r.get("asin")
        if not d or not k:
            continue
        if s <= d <= e:
            a = cur.setdefault(k, {"sku": k, "asin": r.get("asin") or "", "shop": r.get("shop") or "",
                                   "units": 0.0, "revenue": 0.0})
            a["units"] += m._f(r.get("units"))
            a["revenue"] += m._f(r.get("revenue"))
        elif ps <= d <= pe:
            b = prev.setdefault(k, {"units": 0.0, "revenue": 0.0})
            b["units"] += m._f(r.get("units"))
            b["revenue"] += m._f(r.get("revenue"))

    def ratio_txt(a, b):
        return ("%+.0f%%" % ((a - b) / b * 100)) if b else ("新增" if a else "—")

    top = sorted(cur.values(), key=lambda x: -x["revenue"])[:30]
    sku_rows = []
    for a in top:
        b = prev.get(a["sku"]) or {}
        sku_rows.append([
            a["sku"], a["asin"], a["shop"],
            "{:,.0f}".format(a["units"]), "{:,.0f}".format(b.get("units") or 0),
            ratio_txt(a["units"], b.get("units") or 0),
            c.money_usd(a["revenue"]), c.money_usd(b.get("revenue") or 0),
            ratio_txt(a["revenue"], b.get("revenue") or 0),
        ])
    sku_html = hr.section(
        "SKU 明细 Top30（本期 vs 上期，按本期销售额）",
        hr.table_filterable(hr.table(
            ["SKU 编码", "ASIN", "店铺", "本期销量", "上期销量", "销量环比",
             "本期销售额USD", "上期销售额USD", "销售额环比"],
            sku_rows, align_right={3, 4, 5, 6, 7, 8}), "period-sku"))

    burn = {}
    for r in m.load("ads_asin_daily"):
        d = m.row_date(r)
        if not d or not (s <= d <= e):
            continue
        k = (r.get("shop") or "", r.get("campaign") or "未命名")
        a = burn.setdefault(k, {"spend": 0.0, "orders": 0.0, "sales": 0.0})
        a["spend"] += m._f(r.get("spend"))
        a["orders"] += m._f(r.get("orders"))
        a["sales"] += m._f(r.get("sales"))
    burn_rows = [[shop, name, "$%.0f" % a["spend"], "$%.0f" % a["sales"],
                  "{:.0f}".format(a["orders"]), "先查搜索词/竞价/预算"]
                 for (shop, name), a in sorted(burn.items(), key=lambda kv: -kv[1]["spend"])
                 if a["spend"] >= 30 and a["orders"] <= 0][:10]
    burn_html = hr.section(
        "广告烧钱 Campaign（本期花费 ≥$30 且 0 单，%d 个）" % len(burn_rows),
        hr.table(["店铺", "Campaign", "本期花费USD", "广告销售额USD", "订单", "建议"], burn_rows,
                 align_right={2, 3, 4}) if burn_rows else "<p>本期无烧钱 Campaign。</p>")

    inv = m.load("inventory_daily")
    inv_days = m.table_dates(inv)
    inv_day = inv_days[-1] if inv_days else ""
    u28 = m.recent_units_by_sku(m.load("sales_daily"), 28)
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
    inv_rows = [[k, asin, shop, "%.0f" % avail, "%.1f" % dos, "立即补货"]
                for dos, k, asin, shop, avail in crit[:10]]
    inv_html = hr.section(
        "库存急件 Top10（可售 <10 天，快照 %s）" % inv_day,
        hr.table(["SKU 编码", "ASIN", "店铺", "FBA可售", "可售天数", "动作"], inv_rows,
                 align_right={3, 4}) if inv_rows else "<p>无急件。</p>")

    reviews = []
    snap_dir = ROOT / "data" / "raw" / "review"
    if snap_dir.exists():
        import json as _json
        files = sorted(snap_dir.glob("*.json"))
        if files:
            snap = _json.loads(files[-1].read_text())
            for asin, items in (snap.get("items") or {}).items():
                for it in items:
                    if (it.get("star") or 5) <= 3 and s <= str(it.get("date") or "")[:10] <= e:
                        reviews.append([asin, str(it.get("date"))[:10], "%s 星" % it.get("star"),
                                        (it.get("title") or "")[:40], (it.get("content") or "")[:60]])
    rev_html = hr.section(
        "本期新差评（≤3 星，%d 条；来源最新评论快照）" % len(reviews),
        hr.table(["ASIN", "日期", "星级", "标题", "内容摘要"], reviews[:10])
        if reviews else "<p>本期快照内无新增差评（或评论快照未覆盖本期）。</p>")

    return sku_html + burn_html + inv_html + rev_html


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--period", choices=["week", "month"], default="week")
    ap.add_argument("--anchor", default="", help="week: 2026-W44；month: 2026-10")
    args = ap.parse_args()

    shops_cfg = json.loads(SHOPS_JSON.read_text(encoding="utf-8"))["shops"]
    idx, _gran = load_index(args.period)
    if not idx:
        print("没有 shop_daily 数据（先跑 scripts/fetch_lingxing.py）")
        return 2  # 2=数据缺失

    if args.period == "week":
        s, e, ps, pe, ys, ye = week_bounds(args.anchor or None)
        label = "%s ~ %s（ISO 周）" % (s.isoformat(), e.isoformat())
        p_label = "%s ~ %s" % (ps.isoformat(), pe.isoformat())
    else:
        s, e, ps, pe, ys, ye = month_bounds(args.anchor or None)
        label = "%s 月" % s.strftime("%Y-%m")
        p_label = "%s" % ps.strftime("%Y-%m")

    cur_by_shop, cur, cur_days = agg(idx, s, e, granularity=_gran)
    prev_by_shop, prev, prev_days = agg(idx, ps, pe, granularity=_gran)
    yoy_by_shop, yoy, yoy_days = agg(idx, ys, ye, granularity=_gran)
    if not cur_by_shop:
        print("本期（%s）没有数据。先跑 scripts/fetch_lingxing.py 补齐历史。" % label)
        return 2

    # ---- 可比性判定（必须最先算：KPI/结论/明细都要用它决定敢不敢比）----
    # 粒度决定"期望覆盖多少"：日粒度看天数、月粒度看月数。
    # 月报读的是 shop_monthly，一个区间天然只有 1 个月；拿 31 天当期望会永远判不可比。
    if _gran == "month":
        period_days = 1
        prev_days_expected = 1
        yoy_days_expected = 1
    else:
        period_days = (e - s).days + 1
        prev_days_expected = (pe - ps).days + 1
        yoy_days_expected = (ye - ys).days + 1
    prev_incomplete = prev_days > 0 and prev_days < prev_days_expected * 0.7
    yoy_incomplete = yoy_days > 0 and yoy_days < yoy_days_expected * 0.7
    cur_incomplete = cur_days < period_days * 0.7

    # ---- KPI ----
    def kpi(label_txt, key, fmt, invert=False):
        v, p, y = cur.get(key), prev.get(key), yoy.get(key)
        d = None if (prev_incomplete or not p) else ratio(v, p)
        if y and not yoy_incomplete and v is not None:
            yt = "%+.0f%%" % ((v - y) / y * 100)
        else:
            yt = "不可用"
        return {"label": label_txt, "value": fmt(v), "delta": d,
                "delta_good": not invert, "note": "同比 %s" % yt}

    tacos = cur["spend"] / cur["revenue"] if cur["revenue"] else None
    ptacos = prev["spend"] / prev["revenue"] if prev["revenue"] else None
    cards = [
        kpi("销售额(USD)", "revenue", c.money_usd),
        kpi("销量(件)", "units", lambda v: c._fmt(v)),
        kpi("广告花费", "spend", c.money_usd, invert=True),
        {"label": "ACOS", "value": c.pct_int((cur["spend"] / cur["ad_sales"]) if cur["ad_sales"] else None),
         "delta": ratio((cur["spend"] / cur["ad_sales"]) if cur["ad_sales"] else None, ptacos and (prev["spend"] / prev["ad_sales"] if prev["ad_sales"] else None)),
         "delta_good": False, "note": "花费÷广告销售额"},
        {"label": "TACOS", "value": c.pct_int(tacos), "delta": ratio(tacos, ptacos),
         "delta_good": False, "note": "花费÷总销售额"},
        {"label": "FBA 可售(件)", "value": c._fmt(cur.get("fba_available")), "note": "期末快照·仅FBA"},
    ]

    # ---- 趋势：近 12 个周期 ----
    trend_labels, trend_vals = [], []
    cur_start = s
    for i in range(TREND_PERIODS - 1, -1, -1):
        if args.period == "week":
            ps_i = cur_start - dt.timedelta(weeks=i)
            pe_i = ps_i + dt.timedelta(days=6)
            _, tot, _ = agg(idx, ps_i, pe_i, granularity=_gran)
            trend_labels.append("%02d/%02d" % (ps_i.month, ps_i.day))
        else:
            y, mo = cur_start.year, cur_start.month - i
            while mo <= 0:
                y, mo = y - 1, mo + 12
            ps_i = dt.date(y, mo, 1)
            pe_i = (ps_i.replace(day=28) + dt.timedelta(days=4)).replace(day=1) - dt.timedelta(days=1)
            _, tot, _ = agg(idx, ps_i, pe_i, granularity=_gran)
            trend_labels.append("%d-%02d" % (y, mo))
        trend_vals.append(tot["revenue"] or None)

    # ---- 店铺贡献 ----
    hbars, donut_parts, shop_rows = [], [], []
    for shop, acc in sorted(cur_by_shop.items(), key=lambda kv: -kv[1]["revenue"]):
        disp = shops_cfg.get(shop, {}).get("display", shop)
        pv = prev_by_shop.get(shop, {}).get("revenue")
        r = None if prev_incomplete else ratio(acc["revenue"], pv)
        hbars.append({"label": disp, "value": acc["revenue"],
                      "note": (("环比%+.0f%%" % (r * 100)) if r is not None else
                               ("上期不完整" if prev_incomplete else "无上期")),
                      "color": c.GREEN if (r or 0) >= 0 else c.RED})
        donut_parts.append({"label": disp, "value": acc["revenue"]})
        yv = yoy_by_shop.get(shop, {}).get("revenue")
        row = [
            disp, c._fmt(acc["units"]), c.money_usd(acc["revenue"]),
            c.pct_int((acc["spend"] / acc["ad_sales"]) if acc["ad_sales"] else None),
            ("%+.0f%%" % (r * 100)) if r is not None else "不可比",
            ("%+.0f%%" % (((acc["revenue"] - yv) / yv) * 100)) if (yv and not yoy_incomplete) else "不可用",
        ]
        if args.period == "month":
            # 月报才放目标达成：周报表里塞月目标会被读成"这周只完成 20%"
            mt = bm.shop_monthly_target_usd(shop)
            row.append(("%.0f%%" % (acc["revenue"] / mt * 100)) if mt else "—")
        shop_rows.append(row)

    # ---- 结论条 ----
    rev_d = None if (prev_incomplete or prev_days == 0) else ratio(cur["revenue"], prev["revenue"])
    yoy_d = None if (yoy_incomplete or yoy_days == 0) else ratio(cur["revenue"], yoy["revenue"])
    if yoy_d is not None:
        yoy_txt = "同比 %+.0f%%" % (yoy_d * 100)
    elif yoy_days == 0:
        yoy_txt = "同比不可用（无去年同期数据）"
    else:
        yoy_txt = "同比不可用（去年同期仅覆盖 %d 天）" % yoy_days

    if cur_incomplete:
        banner_txt, level = ("本期 %s 数据仅覆盖 %d/%d 天，数字偏低，不建议直接与上期比"
                             % (label, cur_days, period_days)), "warn"
    elif rev_d is None:
        reason = ("上期覆盖 %d/%d 天，环比较失真不展示" % (prev_days, prev_days_expected)
                  if prev_incomplete else "无上期基线")
        banner_txt, level = ("本期 %s 销售额 %s，%s；%s"
                             % (label, c.money_usd(cur["revenue"]), reason, yoy_txt)), "warn"
    else:
        level = "good" if rev_d >= 0 else ("bad" if rev_d <= -0.1 else "warn")
        banner_txt = "本期 %s 销售额 %s，环比 %+.0f%%，%s" % (
            label, c.money_usd(cur["revenue"]), rev_d * 100, yoy_txt)

    # ---- 注意事项（固定一节）----
    notes = [
        "长尾款日波动大：<b>周/月报是主监控口径</b>，日级异动只作线索；销售额环比 ≤-10% 关注、≤-30% 紧急。",
        "ACOS/TACOS 绝对值只说明广告效率高低；<b>成本结构未校准，不能据此判定盈亏</b>（不要当盈亏平衡 ACOS 用）。",
        "可比性：本期是否含大促、断货、新店起量、汇率波动——请在会上人工补充，机器不猜。",
        ("数据完整度：本期覆盖 <b>%d 个月</b>（月粒度按整月汇总）；缺月会拉低本期数字。" % cur_days
         if _gran == "month" else
         "数据完整度：本期覆盖 <b>%d 天</b>（周报应 7 天）；缺失日会拉低本期数字。" % cur_days),
        ("历史覆盖：上期 %d 个月、去年同期 %d 个月%s。" % (
            prev_days, yoy_days, "" if yoy_days else "（<b>同比不可用</b>）")
         if _gran == "month" else
         "历史覆盖：上期 %d 天、去年同期 %d 天%s。" % (
            prev_days, yoy_days, "" if yoy_days else "（<b>同比不可用</b>）")),
        "库存口径：FBA 可售件数，在途/本地仓/海外仓不在内，禁止跨站点相加。",
        "币种：领星 USD 原值，不做汇率换算；跨店同币种相加。",
    ]
    notes_html = "".join("<li>%s</li>" % n for n in notes)

    # ---- 年度目标进度（只在月报显示；周报按月算没意义）----
    progress_html = ""
    if args.period == "month":
        prog = bm.revenue_progress()
        if prog.get("ready"):
            month_rev = cur.get("revenue") or 0
            month_pct = month_rev / prog["month_target_usd"] if prog["month_target_usd"] else None
            lead = "领先" if prog["on_track"] else "落后"
            dpp = (prog["pct"] - prog["time_pct"]) * 100
            foot = ("年度累计达成 %.1f%% · 时间进度 %.1f%% · <b>%s %.1f 个点</b>"
                    " · 剩余 %d 个月月均需 $%s" % (
                        prog["pct"] * 100, prog["time_pct"] * 100, lead, abs(dpp),
                        prog["months_left"], c._fmt(round(prog["need_per_month_usd"]))
                        if prog.get("need_per_month_usd") else "-"))
            if month_pct is not None:
                foot += "；<b>本月达成月目标 %.1f%%</b>（$%s / $%s）" % (
                    month_pct * 100, c._fmt(round(month_rev)),
                    c._fmt(round(prog["month_target_usd"])))
            progress_html = hr.section(
                "%s 年度销售目标（目标 $%s）" % (
                    prog["year"], c._fmt(round(prog["target_usd"]))),
                hr.progress(prog["actual_usd"], prog["target_usd"], prog["time_pct"], foot=foot))
        else:
            progress_html = hr.section("年度目标", "<p>未设定（config/targets.json）。</p>")

    body = (
        hr.banner(banner_txt, level)
        + c.kpi_cards(cards)
        + progress_html
        + hr.section("近 %d 个周期趋势" % TREND_PERIODS,
                     c.line_chart(trend_labels, [{"name": "销售额", "values": trend_vals}],
                                  title="销售额（USD/%s）" % ("周" if args.period == "week" else "月"),
                                  y_fmt="money"))
        + hr.section("店铺贡献（本期 %s）" % label,
                     c.hbar_chart(hbars, title="销售额对比（USD）")
                     + '<div style="display:flex;gap:12px;flex-wrap:wrap">'
                     + c.donut(donut_parts, w=320, h=250, title="本期占比") + "</div>")
        + hr.section("分店明细" + ("（末列为该店月目标达成）" if args.period == "month" else ""),
                     hr.table(
                         ["店铺", "销量", "销售额", "ACOS", "环比", "同比"]
                         + (["目标达成"] if args.period == "month" else []),
                         shop_rows, align_right={1, 2, 3, 4, 5, 6}))
        + detail_sections(s, e, ps, pe)
        + hr.methodology([
            ["环比", "(本期 − 上期) ÷ 上期；上期覆盖 <70% 时判不可比不展示"],
            ["同比", "(本期 − 去年同期) ÷ 去年同期；周报去年同期按 ISO 周对齐；日粒度仅 90 天，周同比不可得时如实标注；月报同比读 shop_monthly（24 个月）"],
            ["主监控口径", "长尾款日波动大，以周/月为主：销售额环比 ≤-10% 关注、≤-30% 紧急；日级异动只作线索"],
            ["ACOS / TACOS", "ACOS = 广告花费 ÷ 广告销售额；TACOS = 广告花费 ÷ 总销售额；成本未校准，不作盈亏判定"],
            ["广告烧钱", "本期 Campaign 花费 ≥$30 且 0 订单 → 先查搜索词/竞价/预算"],
            ["库存急件", "可售天数 = FBA 可售 ÷ 近 28 天等效日均销量；<10 天立即补货，10–21 天本周补货"],
            ["金额口径", "领星 USD 原值，不做汇率换算；下单口径；店铺组多站合并"],
        ])
        + hr.section("⚠ 本期注意事项", '<ul class="plain">%s</ul>' % notes_html)
        + render_attribution(cur, prev, cur_by_shop, prev_by_shop, s, e, ps, pe, shops_cfg)
    )
    _src = "shop_monthly（月粒度）" if _gran == "month" else "shop_daily（日粒度）"
    footer = ("口径：%s（领星 total_sum）· USD · 下单口径 · 跨店相加；" % _src +
              "毛利/利润未校准不展示；金额整数显示。本期 %s（%s），上期 %s。"
              % (label, "完整 %d 天" % cur_days, p_label))
    html = hr.render(
        title="%s经营复盘" % ("周" if args.period == "week" else "月"),
        subtitle="%s · 各店铺组" % label,
        meta="生成 %s" % dt.date.today().isoformat(),
        banner_html="", body_html=body, footer=footer)
    slug = ("week_%s" % s.isoformat()) if args.period == "week" else ("month_%s" % s.strftime("%Y-%m"))
    out = hr.save(html, OUT_DIR / ("%s_review.html" % slug))
    print("✓ %s复盘 → %s" % ("周" if args.period == "week" else "月", out))
    print("  本期 %s：销售额 %s，环比 %s，同比 %s" % (
        label, c.money_usd(cur["revenue"]),
        ("%+.0f%%" % (rev_d * 100)) if rev_d is not None else "无基线",
        ("%+.0f%%" % (yoy_d * 100)) if yoy_d is not None else "不可用"))


if __name__ == "__main__":
    main()
