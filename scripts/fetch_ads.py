#!/usr/bin/env python3
"""拉广告活动（campaign）级日数据 → data/normalized/ads_daily.csv。

为什么单独一个脚本：`shop_daily` 只有店级汇总（花费/ACOS 一个数），
广告诊断要看"哪条 campaign 在烧钱、哪条有花费没单"，必须 campaign 粒度。

用法：
  python3 scripts/fetch_ads.py --days 7            # 拉最近 7 天（增量，已有的跳过）
  python3 scripts/fetch_ads.py --days 30 --force   # 强制重拉（覆盖已有日期）
  python3 scripts/fetch_ads.py --shops shop_a --days 3

口径与坑：
- report_date 是**范围**字符串（"2026-11-01 - 2026-11-03"），所以按天逐日调；
- 领星在 sales=0 时把 acos 返回成 99999999（哨兵值，不是真 ACOS），这里统一转 None；
- 广告店铺 profile_id 与 sid 的对应从 ad_auth_shops 拿，按 sid 归到店铺组；
- 限流 QPS=1：每个请求间隔 1.1 秒，别改成并发。
"""
import argparse
import csv
import io
import json
import os
import sys
import time
import urllib.error
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "skills" / "_shared"))
import metrics as m          # noqa: E402
import mcp_client as mc      # noqa: E402

TABLE = "ads_daily"
ASIN_TABLE = "ads_asin_daily"
ASIN_COLS = ["date", "shop", "profile_id", "asin", "sku", "campaign_id", "campaign",
             "ad_group_id", "spend", "sales", "orders", "clicks", "impressions",
             "acos", "cpc", "currency"]
# 列名与 amz-sku-daily 对齐：它读 spend / campaign / sales / units（不是 spends）
COLS = ["date", "shop", "profile_id", "campaign_id", "campaign",
        "spend", "sales", "orders", "clicks", "impressions",
        "acos", "cpc", "cvr", "budget", "state", "serving_status", "currency"]
# 领星用这些值表示"没有意义"（sales=0 时 ACOS 无穷大）
SENTINEL_GE = 1e6


def load_shops():
    return json.loads((ROOT / "config" / "shops.json").read_text(encoding="utf-8"))["shops"]


def norm_num(v):
    """领星的数字是字符串，还带哨兵值。"""
    n = m.num(v)
    if n is None:
        return None
    if abs(n) >= SENTINEL_GE:      # ACOS 99999999 = 没销售，不是真的 9999 万
        return None
    return n


def norm_pct(v):
    """ACOS 归一化成小数。

    领星返回的是**百分数**（565 表示 565%，26.76 表示 26.76%），
    直接当小数用会让 `acos >= 0.25` 永远成立——2026-11-04 实测
    1537 条 ASIN 级里有 17 条被误报 critical，全是这个原因。
    判断规则：>1 就当百分数除以 100；<=1 认为已经是小数（兼容别的数据源）。
    """
    n = norm_num(v)
    if n is None:
        return None
    return n / 100.0 if n > 1 else n


def profile_map(client):
    """ad_auth_shops → {profile_id: (shop_group, sid)}，按 sid 归到店铺组。"""
    shops = load_shops()
    sid2shop = {}
    for name, cfg in shops.items():
        # sids 是逗号分隔字符串（"1001,1002"），不是列表——直接遍历会逐字符拆
        raw = cfg.get("sids") or ""
        items = raw if isinstance(raw, (list, tuple)) else str(raw).split(",")
        for sid in items:
            sid = str(sid).strip()
            if sid:
                sid2shop[sid] = name
    d = mc.lingxing_action(client, "ad_auth_shops", {})
    rows = d.get("data") if isinstance(d.get("data"), list) else (d.get("list") or [])
    out = {}
    for r in rows:
        if not isinstance(r, dict):
            continue
        pid = str(r.get("profile_id") or "")
        sid = str(r.get("sid") or "")
        if pid and sid in sid2shop:
            out[pid] = {"shop": sid2shop[sid], "sid": sid,
                        "country": r.get("country") or ""}
    return out


def have_days(shop, table=None):
    return {m.row_date(r) for r in m.load(table or TABLE)
            if r.get("shop") == shop and m.row_date(r)}


def pull_day(client, profile_id, day):
    """拉某 profile 某一天的全部 campaign。返回 [row]。"""
    d = mc.lingxing_action(client, "ad_campaign_report", {
        "report_date": "%s - %s" % (day, day),
        "profile_ids": [profile_id],
        "page": 1, "length": 1000,
        "sort_field": "spends", "sort_type": "desc"})
    rows = d.get("data") if isinstance(d.get("data"), list) else (d.get("list") or [])
    out = []
    for r in rows:
        if not isinstance(r, dict):
            continue
        out.append({
            "date": day,
            "profile_id": profile_id,
            "campaign_id": str(r.get("campaign_id") or ""),
            "campaign": str(r.get("name") or r.get("campaign_name") or "")[:120],
            "spend": norm_num(r.get("spends")),
            "sales": norm_num(r.get("sales")),
            "orders": norm_num(r.get("orders")),
            "clicks": norm_num(r.get("clicks")),
            "impressions": norm_num(r.get("impressions")),
            "acos": norm_pct(r.get("acos")),
            "cpc": norm_num(r.get("cpc")),
            "cvr": norm_num(r.get("cvr")),
            "budget": norm_num(r.get("daily_budget") or r.get("budget")),
            "state": str(r.get("state") or ""),
            "serving_status": str(r.get("serving_status") or ""),
            "currency": "USD",
        })
    return out


def pull_day_asin(client, profile_id, day):
    """拉某 profile 某一天的 ASIN 级广告数据（ad_campaign_product_report）。

    注意与 campaign 级的接口差异：这个用 profile_id（单数、整数），
    campaign 级用 profile_ids（数组）。混用会报参数校验错。
    返回里有一条没有 asin 的汇总行，跳过它。
    """
    d = mc.lingxing_action(client, "ad_campaign_product_report", {
        "report_date": "%s - %s" % (day, day),
        "profile_id": int(profile_id),
        "page": 1, "length": 1000,
        "sort_field": "spends", "sort_type": "desc"})
    rows = d.get("data") if isinstance(d.get("data"), list) else (d.get("list") or [])
    out = []
    for r in rows:
        if not isinstance(r, dict):
            continue
        asin = str(r.get("asin") or "").strip()
        if not asin:          # 汇总行（全 campaign 合计），不是 ASIN 明细
            continue
        out.append({
            "date": day,
            "profile_id": profile_id,
            "asin": asin,
            "sku": str(r.get("sku") or r.get("msku") or "").strip(),
            "campaign_id": str(r.get("campaign_id") or ""),
            "campaign": str(r.get("campaign_name") or r.get("name") or "")[:120],
            "ad_group_id": str(r.get("ad_group_id") or ""),
            "spend": norm_num(r.get("spends")),
            "sales": norm_num(r.get("sales")),
            "orders": norm_num(r.get("orders")),
            "clicks": norm_num(r.get("clicks")),
            "impressions": norm_num(r.get("impressions")),
            "acos": norm_pct(r.get("acos")),
            "cpc": norm_num(r.get("cpc")),
            "currency": "USD",
        })
    return out


def merge_rows(new_rows, table=None, cols=None, key_fields=None):
    """按 key_fields 合并写入（同键替换、异键保留）。默认 campaign 级表。"""
    table = table or TABLE
    cols = cols or COLS
    key_fields = key_fields or ("shop", "date", "profile_id", "campaign_id")
    out_dir = Path(m.DATA)
    out_dir.mkdir(parents=True, exist_ok=True)
    dst = out_dir / (table + ".csv")
    keys = {tuple(r.get(k) for k in key_fields) for r in new_rows}
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


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=7, help="拉最近 N 天（默认 7）")
    ap.add_argument("--shops", default="", help="逗号分隔店铺组，缺省全部")
    ap.add_argument("--force", action="store_true", help="忽略已有日期，强制重拉")
    ap.add_argument("--level", default="both", choices=["campaign", "asin", "both"],
                    help="campaign=活动级聚合 / asin=商品级明细（库存和广告都要看到每个 ASIN 用这个）/ both")
    args = ap.parse_args()

    import datetime as dt
    days = [(dt.date.today() - dt.timedelta(days=i)).isoformat()
            for i in range(args.days, 0, -1)]   # 从早到晚，日志好读

    client = mc.lingxing_client()
    pmap = profile_map(client)
    if not pmap:
        print("没有广告授权店铺（ad_auth_shops 返回空）——先在领星授权广告账号")
        return 2
    wanted = [s.strip() for s in args.shops.split(",") if s.strip()] or list(load_shops())
    targets = [(pid, info) for pid, info in pmap.items() if info["shop"] in wanted]
    print("广告 profile %d 个（店铺组：%s）" % (
        len(targets), "、".join(sorted({i["shop"] for _, i in targets}))))

    levels = ["campaign", "asin"] if args.level == "both" else [args.level]
    grand_total = 0
    for level in levels:
        table = TABLE if level == "campaign" else ASIN_TABLE
        cols = COLS if level == "campaign" else ASIN_COLS
        keys = (("shop", "date", "profile_id", "campaign_id") if level == "campaign"
                else ("shop", "date", "profile_id", "asin", "campaign_id", "ad_group_id"))
        puller = (lambda pid, day: pull_day(client, pid, day)) if level == "campaign" \
            else (lambda pid, day: pull_day_asin(client, pid, day))
        cache = {} if args.force else {s: have_days(s, table) for s in wanted}
        print("\n—— %s 级（%s）——" % ("活动" if level == "campaign" else "商品/ASIN", table))
        total_new, per_shop_flush = 0, {}
        for pid, info in sorted(targets, key=lambda x: (x[1]["shop"], x[1]["country"])):
            shop = info["shop"]
            for day in days:
                if day in cache.get(shop, set()):
                    continue
                rows = _with_retry(lambda: puller(pid, day))
                for r in rows:
                    r["shop"] = shop
                per_shop_flush.setdefault(shop, []).extend(rows)
                print("  · %s %s %s：%d 条" % (shop, info["country"], day, len(rows)))
                time.sleep(1.1)   # 领星限流 QPS=1
            # 每店拉完立刻落盘（拉多天时中途断了不白跑）
            if per_shop_flush.get(shop):
                dst, kept, n = merge_rows(per_shop_flush[shop], table, cols, keys)
                total_new += n
                print("  ✓ %s 已落盘 %d 行（文件现有 %d 行）" % (shop, n, kept + n))
                per_shop_flush[shop] = []
        if total_new:
            print("✓ %s 新增 %d 行" % (table, total_new))
        else:
            print("  %s 无新增（缓存命中）" % table)
        grand_total += total_new

    print("\n合计新增 %d 行（level=%s）" % (grand_total, args.level))
    return 0


if __name__ == "__main__":
    try:
        _rc = main()
        import metrics as _m
        _rows = _m.load("ads_asin_daily")
        _dates = _m.table_dates(_rows)
        _m.write_fetch_status("ads", _rc in (0, None), "rc=%s" % _rc,
                              rows=len(_rows), min_date=_dates[0] if _dates else "",
                              max_date=_dates[-1] if _dates else "")
        sys.exit(_rc or 0)
    except Exception as _e:
        try:
            import metrics as _m
            _m.write_fetch_status("ads", False, str(_e)[:200])
        except Exception:
            pass
        raise
