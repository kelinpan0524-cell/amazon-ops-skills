#!/usr/bin/env python3
"""拉利润报表（含采购成本、毛利）→ data/normalized/profit_daily.csv。

## 数据来源
领星 `query_order_profit_list`（订单利润报表）。字段名称有坑，说明写清楚：
- **采购成本**：`avg_purchase_costs`（单件均价）、`purchase_costs`（合计）
- **毛利**：`gross_profit` / `gross_margin`
  这个名字容易误解——它不是"毛利"，是**扣完采购成本 + FBA 配送费 + 佣金之后**的数，
  验算：销售额 - 采购 - 配送费 - 佣金 + 运费补贴 = gross_profit（实测对得上）
- `total_costs` **只等于采购成本**，不含配送费和佣金，不能用它算毛利
- **头程运费没录**：`proportion_of_cg_transport` 实测恒为 0
  所以这个毛利率是**上限值**，真实毛利要再扣头程

## 覆盖率
实测 200 个 MSKU 里只有 103 个（52%）录了采购成本。没录的成本字段为 0，
这类行 `has_cost=0`，统计时要排除（不能把"没录"当成"成本为 0"）。

## 口径
- 日期：按天拉（接口是日期范围汇总，传 start=end=某天）
- 维度：接口返回 ASIN + sid（没有 MSKU，SKU 靠 asin→sku 映射补）

用法：
  python3 scripts/fetch_profit.py --days 7        # 拉最近 7 天（增量）
  python3 scripts/fetch_profit.py --days 30 --force
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

TABLE = "profit_daily"
COLS = ["date", "shop", "sid", "asin", "sku", "item_name",
        "revenue", "purchase_cost", "avg_purchase_cost",
        "fulfillment_fee", "selling_fee", "shipping_cost",
        "gross_profit", "gross_margin", "has_cost", "currency"]
SENTINEL_GE = 1e6


def load_shops():
    return json.loads((ROOT / "config" / "shops.json").read_text(encoding="utf-8"))["shops"]


def sid2shop():
    out = {}
    for name, cfg in load_shops().items():
        raw = cfg.get("sids") or ""
        items = raw if isinstance(raw, (list, tuple)) else str(raw).split(",")
        for s in items:
            s = str(s).strip()
            if s:
                out[s] = name
    return out


def asin2sku():
    """ASIN → SKU（利润接口不返回 MSKU，靠这张映射补）。"""
    out = {}
    for tbl in ("sales_daily", "inventory_daily"):
        for r in m.load(tbl):
            a = (r.get("asin") or "").strip()
            s = (r.get("sku") or "").strip()
            if a and s and a not in out:
                out[a] = s
    return out


def norm_num(v):
    n = m.num(v)
    if n is None:
        return None
    if abs(n) >= SENTINEL_GE:
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
            print("    ! 网络抖动，%.0f 秒后重试" % wait)
            time.sleep(wait)
    raise last


def pull_day(client, day):
    """拉某一天的利润行。返回 [row]。"""
    d = mc.lingxing_action(client, "query_order_profit_list", {
        "start_date": day, "end_date": day,
        "currency_type": "USD", "summary_field": "asin", "turn_on_summary": "1",
        "sort_type": "desc", "length": "200", "offset": "0",
        "source_service": "mcp", "external_service_mark": 1,
        "search_type": 0, "service_type": 1, "date_summary_type": 1})
    data = d.get("data")
    rows = data if isinstance(data, list) else (data or {}).get("list") or []
    s2sh = sid2shop()
    out = []
    for r in rows:
        if not isinstance(r, dict):
            continue
        asins = r.get("asin_list") or []
        asin = str(asins[0]).strip() if asins else ""
        sids = r.get("sids") or []
        sid = str(sids[0]).strip() if sids else ""
        avg_cost = norm_num(r.get("avg_purchase_costs"))
        out.append({
            "date": day,
            "shop": s2sh.get(sid, ""),
            "sid": sid,
            "asin": asin,
            "sku": "",      # 下面统一补
            "item_name": str(r.get("item_name") or "")[:100],
            "revenue": norm_num(r.get("amount")),
            "purchase_cost": norm_num(r.get("purchase_costs")),
            "avg_purchase_cost": avg_cost,
            "fulfillment_fee": norm_num(r.get("fulfillment_fee")),
            "selling_fee": norm_num(r.get("selling_fee")),
            "shipping_cost": norm_num(r.get("shipping_cost")),
            "gross_profit": norm_num(r.get("gross_profit")),
            "gross_margin": norm_num(r.get("gross_margin")),
            # 没录采购成本的行：has_cost=0，统计时要排除（不能当成本 0 算）
            "has_cost": 1 if (avg_cost or 0) > 0 else 0,
            "currency": "USD",
        })
    return out


def merge_rows(new_rows):
    """按 (date, shop, sid, asin) 合并写入。"""
    out_dir = Path(m.DATA)
    out_dir.mkdir(parents=True, exist_ok=True)
    dst = out_dir / (TABLE + ".csv")
    uniq = {}
    for r in new_rows:
        uniq[(r["date"], r["shop"], r["sid"], r["asin"])] = r
    keys = set(uniq)
    kept = []
    if dst.exists():
        for r in csv.DictReader(io.StringIO(dst.read_text(encoding="utf-8"))):
            if (r.get("date"), r.get("shop"), r.get("sid"), r.get("asin")) in keys:
                continue
            kept.append(r)
    merged = kept + [{k: ("" if v is None else v) for k, v in r.items()}
                     for r in uniq.values()]
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=COLS, extrasaction="ignore")
    w.writeheader()
    for r in merged:
        w.writerow(r)
    dst.write_text(buf.getvalue(), encoding="utf-8")
    return dst, len(kept), len(uniq)


def have_days(shop):
    return {m.row_date(r) for r in m.load(TABLE)
            if r.get("shop") == shop and m.row_date(r)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=7)
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()

    import datetime as dt
    days = [(dt.date.today() - dt.timedelta(days=i)).isoformat()
            for i in range(args.days, 0, -1)]

    client = mc.lingxing_client()
    a2s = asin2sku()
    have = set() if args.force else {m.row_date(r) for r in m.load(TABLE) if m.row_date(r)}

    total, with_cost, per_day = 0, 0, {}
    for day in days:
        if day in have:
            print("  · %s 已有，跳过" % day)
            continue
        rows = _with_retry(lambda: pull_day(client, day))
        for r in rows:
            r["sku"] = a2s.get(r["asin"], "")
        per_day[day] = rows
        n_cost = sum(r["has_cost"] for r in rows)
        total += len(rows)
        with_cost += n_cost
        print("  · %s：%d 行，其中 %d 行有采购成本" % (day, len(rows), n_cost))
        # 每天拉完就落盘（拉多天时中途断了不白跑）
        if rows:
            merge_rows(rows)
        time.sleep(1.1)

    if not total:
        print("无新增（缓存命中）")
        return 0
    dst, kept, n = merge_rows([r for rows in per_day.values() for r in rows])
    print("✓ 新增 %d 行 → %s（文件现有 %d 行）" % (n, dst.name, kept + n))
    print("  其中有采购成本的 %d 行（%.0f%%）" % (with_cost, with_cost / total * 100))
    if with_cost < total:
        print("  ! 其余 %d 行没录采购成本，统计时要排除（已标 has_cost=0）" % (total - with_cost))
    return 0


if __name__ == "__main__":
    sys.exit(main())
