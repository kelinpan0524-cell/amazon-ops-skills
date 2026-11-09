#!/usr/bin/env python3
"""SKU 级「当日明细」共享构建器。

每日经营简报 / 单店日报 / 多店总览都要同一张 SKU 级明细表：
销量（sales_daily）× 广告（ads_asin_daily）× 库存（inventory_daily）三表按 SKU 关联，
避免各技能各写一套口径漂移。

口径：
  - 当日 = sales_daily 表内最新一天（领星当天数据未产齐时自然回退到最近完整日）；
  - 可售天数 = 当前 FBA 可售 ÷ 日均销量，日均按表内实际跨度折算成近 28 天等效量；
  - 缺数（fba_available 空、无广告行）留空显示「—」，不当 0。
"""
import metrics as m


def _f(v):
    return m._f(v)


def _num(v):
    return m.num(v)


def latest_sales_day(sales_rows):
    dates = m.table_dates(sales_rows)
    return dates[-1] if dates else None


def sku_daily_rows(shop=None, day=None):
    """返回当日 SKU 明细行列表（dict）。shop=None 表示全部店铺组。"""
    sales_all = [r for r in m.load("sales_daily") if not shop or r.get("shop") == shop]
    ads_all = [r for r in m.load("ads_asin_daily") if not shop or r.get("shop") == shop]
    inv_all = [r for r in m.load("inventory_daily") if not shop or r.get("shop") == shop]

    day = day or latest_sales_day(sales_all)
    if not day:
        return [], None

    # 近 28 天窗口等效销量（去年同期回补段不参与，避免日均被稀释）
    u28 = m.recent_units_by_sku(sales_all, 28)

    agg = {}

    def _slot(r):
        k = r.get("sku") or r.get("asin")
        s = agg.setdefault(k, {
            "sku": k, "asin": r.get("asin") or "", "shop": r.get("shop") or "",
            "product": (r.get("product_name") or "").strip(),
            "units": 0.0, "revenue": 0.0, "sessions": 0.0,
            "spend": 0.0, "ad_sales": 0.0, "orders": 0.0, "clicks": 0.0,
            "has_ads": False, "fba": None, "inbound": None,
        })
        if not s["product"] and (r.get("product_name") or "").strip():
            s["product"] = r["product_name"].strip()
        if not s["asin"] and r.get("asin"):
            s["asin"] = r["asin"]
        return s

    for r in sales_all:
        if m.row_date(r) != day:
            continue
        s = _slot(r)
        s["units"] += _f(r.get("units"))
        s["revenue"] += _f(r.get("revenue"))
        s["sessions"] += _f(r.get("sessions"))

    for r in ads_all:
        if m.row_date(r) != day:
            continue
        s = _slot(r)
        s["spend"] += _f(r.get("spend"))
        s["ad_sales"] += _f(r.get("sales"))
        s["orders"] += _f(r.get("orders"))
        s["clicks"] += _f(r.get("clicks"))
        s["has_ads"] = True

    # 库存取该 SKU 最新一天（不一定等于销量当日）
    inv_latest = {}
    for r in inv_all:
        d = m.row_date(r)
        k = r.get("sku") or r.get("asin")
        if k not in inv_latest or (d or "") >= inv_latest[k][0]:
            inv_latest[k] = (d or "", r)
    for k, (_d, r) in inv_latest.items():
        s = _slot(r)
        s["fba"] = _num(r.get("fba_available"))
        s["inbound"] = _num(r.get("fba_inbound"))

    rows = []
    for k, s in agg.items():
        s["u28"] = u28.get(k, 0.0)
        s["daily_avg"] = s["u28"] / 28.0
        s["dos"] = (m.days_of_supply(s["fba"], s["u28"]) if s["fba"] is not None else None)
        s["acos"] = m.acos(s["spend"], s["ad_sales"]) if s["has_ads"] else None
        rows.append(s)
    # 默认按当日销售额降序，没销量的按可售天数升序排尾
    rows.sort(key=lambda s: (-s["revenue"], s["dos"] if s["dos"] is not None else 9e9))
    return rows, day


def _money(v):
    return "—" if v is None else "${:,.0f}".format(v)


def _int(v):
    return "—" if v is None else "{:,.0f}".format(v)


def sku_table(rows, max_rows=None, table_id="sku-detail", with_product=True):
    """SKU 明细表 HTML（可排序 + 搜索框；飞书预览静态可读，浏览器里可交互）。"""
    import html_report as hr

    show = rows[:max_rows] if max_rows else rows
    headers = ["SKU 编码", "ASIN", "店铺"]
    if with_product:
        headers.append("商品")
    headers += ["销量", "销售额", "广告花费", "ACOS", "订单", "FBA可售", "可售天数"]
    body = []
    for s in show:
        dos = s.get("dos")
        dos_txt = "—" if dos is None else (
            '<b style="color:#dc2626">%.1f</b>' % dos if dos < 10 else
            '<span style="color:#d97706">%.1f</span>' % dos if dos < 21 else "%.1f" % dos)
        r = [s["sku"], s["asin"], s["shop"]]
        if with_product:
            r.append((s["product"] or "")[:38])
        r += [_int(s["units"]), _money(s["revenue"]),
              _money(s["spend"]) if s["has_ads"] else "—",
              ("%.1f%%" % (s["acos"] * 100)) if s.get("acos") is not None else "—",
              _int(s["orders"]) if s["has_ads"] else "—",
              _int(s["fba"]), dos_txt]
        body.append(r)
    right = set(range(len(headers) - 7, len(headers)))
    t = hr.table(headers, body, align_right=right)
    note = ""
    if max_rows and len(rows) > max_rows:
        note = ('<div style="font-size:12px;color:#6b7280;margin:4px 0">共 %d 个 SKU，'
                '按销售额取前 %d 个；完整数据见本地 CSV</div>' % (len(rows), max_rows))
    return note + hr.table_filterable(t, table_id)
