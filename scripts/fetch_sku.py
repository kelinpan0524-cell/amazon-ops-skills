#!/usr/bin/env python3
"""拉 SKU 级数据：销量明细（sales_daily）+ FBA 库存快照（inventory_daily）。

为什么需要它：`shop_daily` 是店级汇总，能回答"这家店昨天卖了多少"，
但回答不了"哪个 SKU 要断货了""哪个 ASIN 在掉"——那两张表是 SKU 级的。

用法：
  python3 scripts/fetch_sku.py --days 7        # 销量明细拉最近 7 天 + 库存拉今天
  python3 scripts/fetch_sku.py --inventory-only  # 只刷库存快照

口径：
- sales_daily 是**按天**的 ASIN 明细（领星产品表现 turn_on_summary=0）；
- inventory_daily 是**当前快照**（FBA 可售/在途），每天都存一份，用来算可售天数；
- 币种统一 USD（领星按 USD 折算，跨币种不做手工加总）。
"""
import argparse
import csv
import io
import json
import sys
import time
import urllib.error
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "skills" / "_shared"))
import metrics as m          # noqa: E402
import mcp_client as mc      # noqa: E402

SALES_TABLE = "sales_daily"
INV_TABLE = "inventory_daily"
SALES_COLS = ["date", "shop", "asin", "sku", "product_name", "units", "revenue",
              "sessions", "conversion", "currency"]
# 列名跟 amz-inventory-alert 对齐（它读 fba_available / fba_inbound）；
# 其余是 SKU 级报表要展示的：产品名（人看得懂）、父 ASIN、预留/不可售/在手。
# 不放 total_onhand：实测它跟 FBA 可售对不上（可售 93 / total_onhand 0），
# 那个字段是含本地仓/在途的另一种口径，混在一张表里必然被读错。
INV_COLS = ["date", "shop", "sid", "asin", "parent_asin", "sku", "fnsku",
            "product_name", "fba_available", "fba_inbound", "fba_reserved",
            "fba_unsellable", "currency"]
SENTINEL_GE = 1e6


def load_shops():
    return json.loads((ROOT / "config" / "shops.json").read_text(encoding="utf-8"))["shops"]


def split_sids(v):
    """shops.json 里的 sids 是逗号分隔的**字符串**（"1001,1002"），不是列表。

    2026-11-04 踩过：直接 for sid in sids 会逐字符遍历，把 "1001" 拆成 1/0/0/1
    发给领星，每个都返回 0 条库存——日志里看到 sid=6、sid=9 这种一位数就是它。
    """
    if isinstance(v, (list, tuple)):
        return [str(x).strip() for x in v if str(x).strip()]
    return [x.strip() for x in str(v or "").split(",") if x.strip()]


def norm_num(v):
    n = m.num(v)
    if n is None:
        return None
    if abs(n) >= SENTINEL_GE:      # 领星的无穷大哨兵（转化率在 0 曝光时会这样）
        return None
    return n


def _with_retry(fn, tries=4, base_delay=2.0):
    last = None
    for i in range(tries):
        try:
            return fn()
        except (urllib.error.URLError, TimeoutError, ConnectionError, OSError) as e:
            last = e
            if i == tries - 1:
                break
            wait = base_delay * (2 ** i)
            print("    ! 网络抖动（%s），%.0f 秒后重试" % (str(e)[:50], wait))
            time.sleep(wait)
    raise last


def merge_rows(table, cols, new_rows, key_fields):
    out_dir = Path(m.DATA)
    out_dir.mkdir(parents=True, exist_ok=True)
    dst = out_dir / (table + ".csv")
    # new_rows 内部也要去重：领星多个 sid（如 1001/1002/1003）会返回同一批库存，
    # 不去重就会同一个 SKU 在表里出现 3 次（2026-11-04 实测 510 行里 2/3 是重复）
    uniq = {}
    for r in new_rows:
        uniq[tuple(r.get(k) for k in key_fields)] = r
    new_rows = list(uniq.values())
    keys = set(uniq)
    kept = []
    if dst.exists():
        for r in csv.DictReader(io.StringIO(dst.read_text(encoding="utf-8"))):
            if tuple(r.get(k) for k in key_fields) in keys:
                continue
            kept.append(r)
    merged = kept + [{k: ("" if v is None else v) for k, v in r.items()} for r in new_rows]
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=cols, extrasaction="ignore")
    w.writeheader()
    for r in merged:
        w.writerow(r)
    dst.write_text(buf.getvalue(), encoding="utf-8")
    return dst, len(kept), len(new_rows)


def have_sales_days(shop):
    return {m.row_date(r) for r in m.load(SALES_TABLE)
            if r.get("shop") == shop and m.row_date(r)}


# ---------------- 销量明细 ----------------

def _sku_from_msku_str(s):
    """从领星的 msku_sid_str 里抠出 SKU。

    格式（2026-11-04 实测）：
      "NI-CA-80822$|$1001$|$B0D62SYW8S$|$null$|$...!$NI-CA-80822$|$1002$|$..."
    段内用 $|$ 分隔，多个 (sku,sid) 组合用 !$ 分隔。
    第 0 段是 SKU、第 1 段是 sid、第 2 段是 ASIN。
    顶层 msku / sku 字段实测是 None，只有这个复合字符串里有货。
    """
    if not s:
        return ""
    first = str(s).split("!$")[0]
    parts = first.split("$|$")
    return parts[0].strip() if parts else ""


def pull_sales_day(client, sids, day):
    """某店组某天的 SKU 明细。返回 [row(不含 shop)]。

    两个坑（2026-11-04 实测）：
    - length 最大 500，传 1000 直接被 422 拒；
    - turn_on_summary 要传 1（"SKU 维度请设置为 1"），传 0 拿不到按 SKU 的汇总。
    """
    d = mc.lingxing_action(client, "query_product_performance_asin_lists", {
        "start_date": day, "end_date": day, "sids": sids,
        "date_type": "purchase", "currency_code": "USD",
        "turn_on_summary": 1, "offset": 0, "length": 500})
    inner = d.get("data")
    rows = inner if isinstance(inner, list) else (inner or {}).get("list") or []
    out = []
    for r in rows:
        if not isinstance(r, dict):
            continue
        asin = str(r.get("asin") or "").strip()
        sku = str(r.get("msku") or r.get("sku") or r.get("seller_sku") or "").strip()
        if not sku:
            sku = _sku_from_msku_str(r.get("msku_sid_str"))
        if not asin and not sku:
            continue
        out.append({
            "date": day,
            "asin": asin,
            "sku": sku,
            "product_name": str(r.get("item_name") or "")[:120],
            "units": norm_num(r.get("volume") or r.get("units")),
            "revenue": norm_num(r.get("amount") or r.get("sales")),
            "sessions": norm_num(r.get("sessions")),
            "conversion": norm_num(r.get("conversion") or r.get("cvr")),
            "currency": "USD",
        })
    return out


# ---------------- FBA 库存快照 ----------------

def pull_inventory(client, sid, day):
    """某店（单 sid）当前 FBA 库存。返回 [row(不含 shop)]。

    字段名以领星实际返回为准（2026-11-04 实测 get_fba_stock_list）：
      afn_fulfillable_quantity  FBA 可售
      afn_inbound_*             三段在途（shipped/receiving/working 相加）
      afn_reserved_quantity     预留（客户订单 + 调仓 + 处理中）
      afn_unsellable_quantity   不可售（破损/退货）
      total_onhand_quantity     在手合计
    length 只接受 20/50/100/200/500/1000，传别的会被 422 拒绝。
    """
    out, offset = [], 0
    for _ in range(10):   # 最多 10 页 × 500 = 5000 SKU，够用
        d = mc.lingxing_action(client, "get_fba_stock_list", {
            "sid": str(sid), "offset": offset, "length": 500,
            "fulfillment_channel_type": "FBA"})
        rows = d.get("list") or (d.get("data") or {}).get("list") or []
        if not rows:
            break
        for r in rows:
            if not isinstance(r, dict):
                continue
            inbound = sum((norm_num(r.get(k)) or 0) for k in (
                "afn_inbound_shipped_quantity",
                "afn_inbound_receiving_quantity",
                "afn_inbound_working_quantity"))
            out.append({
                "date": day,
                "sid": str(sid),
                "asin": str(r.get("asin") or "").strip(),
                "parent_asin": str(r.get("parent_asin_real") or "").strip(),
                "sku": str(r.get("sku") or r.get("seller_sku") or "").strip(),
                "fnsku": str(r.get("fnsku") or "").strip(),
                "product_name": str(r.get("product_name") or "")[:80],
                "fba_available": norm_num(r.get("afn_fulfillable_quantity")),
                "fba_inbound": inbound or 0,
                "fba_reserved": norm_num(r.get("afn_reserved_quantity")),
                "fba_unsellable": norm_num(r.get("afn_unsellable_quantity")),
                "currency": "USD",
            })
        if len(rows) < 500:
            break
        offset += 500
        time.sleep(1.1)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=7, help="销量明细拉最近 N 天（默认 7）")
    ap.add_argument("--start", default="", help="起始日 YYYY-MM-DD（与 --end 搭配回补去年同期）")
    ap.add_argument("--end", default="", help="结束日 YYYY-MM-DD")
    ap.add_argument("--shops", default="", help="逗号分隔店铺组，缺省全部")
    ap.add_argument("--inventory-only", action="store_true", help="只刷库存快照")
    ap.add_argument("--force", action="store_true", help="销量明细忽略缓存强制重拉")
    args = ap.parse_args()

    import datetime as dt
    today = dt.date.today().isoformat()
    shops = load_shops()
    wanted = [s.strip() for s in args.shops.split(",") if s.strip()] or list(shops)
    client = mc.lingxing_client()
    rc = 0

    # ---- 库存快照（轻、每天都刷）----
    inv_rows, n_inv = [], 0
    for shop in wanted:
        for sid in split_sids(shops[shop].get("sids")):
            rows = _with_retry(lambda: pull_inventory(client, sid, today))
            for r in rows:
                r["shop"] = shop
            inv_rows.extend(rows)
            print("  · %s sid=%s 库存 %d 个 SKU" % (shop, sid, len(rows)))
            time.sleep(1.1)
    if inv_rows:
        dst, kept, n = merge_rows(INV_TABLE, INV_COLS, inv_rows, ("date", "shop", "sku", "asin"))
        n_inv = n
        print("✓ 库存快照 %d 行 → %s（文件现有 %d 行）" % (n, dst, kept + n))
    else:
        print("! 库存没拉到数据（检查 get_fba_stock_list 权限）")
        rc = 2

    if args.inventory_only:
        return rc

    # ---- 销量明细（按天，增量）----
    if args.start and args.end:
        s0, e0 = dt.date.fromisoformat(args.start), dt.date.fromisoformat(args.end)
        days = [(s0 + dt.timedelta(days=i)).isoformat() for i in range((e0 - s0).days + 1)]
    else:
        days = [(dt.date.today() - dt.timedelta(days=i)).isoformat()
                for i in range(args.days, 0, -1)]
    total_sales = 0
    for shop in wanted:
        sids = ",".join(split_sids(shops[shop].get("sids")))
        if not sids:
            continue
        have = set() if args.force else have_sales_days(shop)
        shop_rows = []
        for day in days:
            if day in have:
                continue
            rows = _with_retry(lambda: pull_sales_day(client, sids, day))
            for r in rows:
                r["shop"] = shop
            shop_rows.extend(rows)
            print("  · %s %s：%d 个 ASIN" % (shop, day, len(rows)))
            time.sleep(1.1)
        if shop_rows:
            dst, kept, n = merge_rows(SALES_TABLE, SALES_COLS, shop_rows,
                                      ("date", "shop", "sku", "asin"))
            total_sales += n
            print("  ✓ %s 销量落盘 %d 行（文件现有 %d 行）" % (shop, n, kept + n))
    if total_sales:
        print("✓ 本轮新增 %d 行销量明细 → %s" % (total_sales, SALES_TABLE))
    else:
        print("销量明细无新增（缓存命中）")
    return rc


if __name__ == "__main__":
    try:
        _rc = main()
        import metrics as _m
        _sales = _m.load("sales_daily")
        _inv = _m.load("inventory_daily")
        _sd = _m.table_dates(_sales)
        _id = _m.table_dates(_inv)
        _dates = sorted(set(_sd + _id))
        _latest = min(x[-1] for x in (_sd, _id) if x) if _sd and _id else (_dates[-1] if _dates else "")
        _m.write_fetch_status("sku", _rc in (0, None), "rc=%s" % _rc,
                              rows=len(_sales) + len(_inv),
                              min_date=_dates[0] if _dates else "", max_date=_latest)
        sys.exit(_rc or 0)
    except Exception as _e:
        try:
            import metrics as _m
            _m.write_fetch_status("sku", False, str(_e)[:200])
        except Exception:
            pass
        raise
