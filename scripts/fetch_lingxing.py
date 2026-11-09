#!/usr/bin/env python3
"""从领星 MCP 自动拉「店铺 × 天」经营数据，落成 data/normalized/shop_daily.csv。

这是 Mac Mini 定时拉数的地基：替代手工「领星后台导 Excel → import_lingxing.py」。
纯标准库（urllib + json），凭证从环境变量读，永不进 git：
  export LINGXING_MCP_URL="https://openmcp.lingxing.com/mcp-servers/lingxing-mcp"
  export LINGXING_MCP_KEY="<你的 X-Mcp-Key>"

用法：
  python3 scripts/fetch_lingxing.py                    # 重拉全部店铺组最近 3 个完整日
  python3 scripts/fetch_lingxing.py --days 7 --shops shop_a,shop_b
  python3 scripts/fetch_lingxing.py --selftest         # 不联网，验证解析与写表管道

数据口径（写进表里每行的语义）：
  - 日常模式只写已结束日期，不把今天的未完整快照落成正式记录；
  - 最近 N 个完整日每次都重拉校准，不能以“本地已有日期”代替数据完整；
  - 店级销量和销售额同时为 0 时必须完成 SKU 交叉核验或显式 --allow-zero，否则拒绝落盘；
  - 店铺组定义在 config/shops.yaml（sids 来自领星店铺列表，改组只改配置）；
  - 金额一律 USD（领星折算），date_type=purchase（下单口径）；
  - 每天每店一次 total_sum 调用（领星限流 QPS=1，脚本内置节流）；
  - 毛利/利润字段**不落表**（领星口径未校准，仓库红线）；
  - 幂等：同 shop+date 重拉替换旧行，不同日期追加（与 import_lingxing 同语义）。
"""
import argparse
import datetime as dt
import io
import json
import os
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "skills" / "_shared"))
import metrics as m  # noqa: E402  （受限 YAML 解析共用一份）

SHOPS_JSON = ROOT / "config" / "shops.json"
OUT_TABLE = "shop_daily"
MONTH_TABLE = "shop_monthly"
MONTH_COLS = ["shop", "month", "units", "revenue", "net_revenue", "orders", "sessions",
              "page_views", "spend", "ad_sales", "acos", "return_rate", "return_amount",
              "refund_units", "fba_available", "available_inventory", "margin_rate",
              "fetched_at"]
OUT_COLS = ["shop", "date", "units", "revenue", "net_revenue", "orders", "sessions",
            "page_views", "spend", "ad_sales", "acos", "return_rate", "fba_available",
            "available_inventory", "units_yoy_ratio", "fetched_at"]

SAMPLE_TOTAL_SUM = {
    "volume": 58, "amount": "55747.90", "net_amount": "55383.76", "order_items": 58,
    "sessions_total": 434, "page_views_total": 688, "spend": "2241.84",
    "ad_sales_amount": "11186.55", "acos": "0.2004", "return_rate": "0.0517",
    "afn_fulfillable_quantity": 5017, "volume_yoy_ratio": "0.0943",
}


def load_shops():
    cfg = json.loads(SHOPS_JSON.read_text(encoding="utf-8"))
    shops = cfg.get("shops") or {}
    if not isinstance(shops, dict) or not shops:
        sys.exit("config/shops.json 里没有店铺组（shops 段为空）")
    for name, grp in shops.items():
        if not str(grp.get("sids", "")).strip():
            sys.exit("店铺组 %r 缺 sids（领星店铺 ID）" % name)
    return shops


class LingxingMCP:
    """领星 MCP 的最小 Streamable HTTP 客户端（JSON-RPC，纯标准库）。"""

    def __init__(self, url, key):
        self.url = url.rstrip("/")
        self.key = key
        self._id = 0
        self._session = None

    def _post(self, payload):
        req = urllib.request.Request(
            self.url,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json", "Accept": "application/json",
                     "X-Mcp-Key": self.key, **({"mcp-session-id": self._session} if self._session else {})},
            method="POST")
        with urllib.request.urlopen(req, timeout=60) as resp:
            sid = resp.headers.get("mcp-session-id")
            if sid:
                self._session = sid
            body = resp.read().decode("utf-8")
        # streamable HTTP 可能返回 ndjson 多行；取最后一条带 result 的
        for line in reversed([ln for ln in body.splitlines() if ln.strip()]):
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            if "result" in obj or "error" in obj:
                return obj
        raise RuntimeError("MCP 响应里没有 JSON-RPC result：%s…" % body[:200])

    def _call(self, method, params=None):
        self._id += 1
        payload = {"jsonrpc": "2.0", "id": self._id, "method": method}
        if params is not None:
            payload["params"] = params
        obj = self._post(payload)
        if "error" in obj:
            raise RuntimeError("MCP %s 出错：%s" % (method, obj["error"]))
        return obj["result"]

    def initialize(self):
        self._call("initialize", {
            "protocolVersion": "2025-03-26",
            "capabilities": {},
            "clientInfo": {"name": "amz-ops-fetch", "version": "1.0"}})
        try:  # initialized 通知（部分服务端要求；失败不致命）
            self._post({"jsonrpc": "2.0", "method": "notifications/initialized"})
        except Exception:
            pass

    def tool(self, tool_id, arguments):
        # 领星 MCP 只暴露 help/search/action 等少数 MCP 工具，业务工具走 action 的 toolId+params
        res = self._call("tools/call", {"name": "action",
                                        "arguments": {"toolId": tool_id, "params": arguments}})
        text = "".join(part.get("text", "") for part in res.get("content", [])
                       if isinstance(part, dict))
        if res.get("isError"):
            raise RuntimeError("工具 %s 返回错误：%s" % (tool_id, text[:300]))
        data = json.loads(text)
        if not data.get("success", True):
            raise RuntimeError("工具 %s success=false：%s" % (tool_id, str(data.get("msg"))[:200]))
        return data.get("data") or {}


def _with_retry(fn, tries=4, base_delay=2.0):
    """网络抖动重试（指数退避）。

    为什么要：2026-11-04 补 400 天历史时，跑到第 728 个请求时
    领星 MCP 抛 SSL: UNEXPECTED_EOF_WHILE_READING，直接中断整轮。
    单个请求抖一下不该让几百次调用白跑。
    """
    last = None
    for i in range(tries):
        try:
            return fn()
        except (urllib.error.URLError, TimeoutError, ConnectionError, OSError) as e:
            last = e
            if i == tries - 1:
                break
            wait = base_delay * (2 ** i)
            print("  ! 网络抖动（%s），%.0f 秒后重试 %d/%d"
                  % (str(e)[:60], wait, i + 1, tries - 1))
            time.sleep(wait)
    raise last


def recent_complete_days(today, count):
    """最近 N 个已结束日期，排除今天；近期快照每次都要重拉校准。"""
    if count < 1:
        raise ValueError("--days 必须大于 0")
    return [(today - dt.timedelta(days=i)).isoformat() for i in range(count, 0, -1)]


def validate_shop_row(row, sku_rows, allow_zero=False):
    """拦截“店级全零但 SKU 有销售/没有可核验明细”的未完整快照。

    真实全零停业日必须显式传 --allow-zero，避免把接口清晨空快照静默当成正式经营数据。
    SKU 合计只用于否定错误零值，不替代店级汇总，也不要求两个快照金额完全相等。
    """
    units = m.num(row.get("units"))
    revenue = m.num(row.get("revenue"))
    if (units or 0) != 0 or (revenue or 0) != 0 or allow_zero:
        return
    shop, day = row.get("shop"), row.get("date")
    related = [r for r in sku_rows
               if r.get("shop") == shop and m.row_date(r) == day]
    sku_units = sum(m.num(r.get("units")) or 0 for r in related)
    sku_revenue = sum(m.num(r.get("revenue")) or 0 for r in related)
    if related and (sku_units != 0 or sku_revenue != 0):
        raise RuntimeError(
            "%s %s 店级返回全零，但 SKU 明细为 %s 件 / $%.2f；拒绝写入未完整快照"
            % (shop, day, format(sku_units, "g"), sku_revenue))
    raise RuntimeError(
        "%s %s 店级返回全零，且没有可证明真实零销售的 SKU 明细；拒绝写入。"
        "如已人工确认当日确实停业，可使用 --allow-zero" % (shop, day))


def pull_shop_day(client, sids, day):
    """一次产品表现查询（单店组、单日），返回 total_sum。网络抖动自动重试。"""
    data = _with_retry(lambda: client.tool("query_product_performance_asin_lists", {
        "start_date": day, "end_date": day, "sids": sids,
        "date_type": "purchase", "currency_code": "USD",
        "turn_on_summary": 1, "offset": 0, "length": 1}))
    inner = data.get("data") or {}
    ts = inner.get("total_sum")
    if not ts:
        raise RuntimeError("%s %s 没有返回 total_sum" % (sids, day))
    return ts


def have_days(shop):
    """该店在 shop_daily 里已有数据的日期集合（用于增量拉取）。"""
    return {m.row_date(r) for r in m.load("shop_daily")
            if r.get("shop") == shop and m.row_date(r)}


def have_months(shop):
    """该店在 shop_monthly 里已有的月份集合。"""
    return {str(r.get("month", "")).strip() for r in m.load("shop_monthly")
            if r.get("shop") == shop and str(r.get("month", "")).strip()}


def month_range(months: int):
    """最近 N 个完整自然月（不含本月），返回 [(month_str, start_iso, end_iso)]。"""
    first = dt.date.today().replace(day=1)
    out = []
    for i in range(months, 0, -1):
        y, mo = first.year, first.month - i
        while mo <= 0:
            y, mo = y - 1, mo + 12
        s = dt.date(y, mo, 1)
        e = (s.replace(day=28) + dt.timedelta(days=4)).replace(day=1) - dt.timedelta(days=1)
        out.append(("%04d-%02d" % (y, mo), s.isoformat(), e.isoformat()))
    return out


def pull_shop_month(client, sids, start, end):
    """一次查询一个月（领星限制单次跨度 ≤1 年，逐月拉可覆盖任意长历史）。"""
    data = client.tool("query_product_performance_asin_lists", {
        "start_date": start, "end_date": end, "sids": sids,
        "date_type": "purchase", "currency_code": "USD",
        "turn_on_summary": 1, "offset": 0, "length": 1})
    return (data.get("data") or {}).get("total_sum")


def row_from_month(shop, month, ts):
    """total_sum → shop_monthly 一行（保留退货率与退货额，供阈值校准用）。"""
    inv = ts.get("available_inventory")
    inv_total = m.num(inv.get("available_inventory")) if isinstance(inv, dict) else None
    return {
        "shop": shop, "month": month,
        "units": m.num(ts.get("volume")),
        "revenue": m.num(ts.get("amount")),
        "net_revenue": m.num(ts.get("net_amount")),
        "orders": m.num(ts.get("order_items")),
        "sessions": m.num(ts.get("sessions_total")),
        "page_views": m.num(ts.get("page_views_total")),
        "spend": m.num(ts.get("spend")),
        "ad_sales": m.num(ts.get("ad_sales_amount")),
        "acos": m.num(ts.get("acos")),
        "return_rate": m.num(ts.get("return_rate")),
        "return_amount": m.num(ts.get("return_amount")),
        "refund_units": m.num(ts.get("return_goods_count")),
        "fba_available": m.num(ts.get("afn_fulfillable_quantity")),
        "available_inventory": inv_total,
        # 领星给的毛利率是 ERP 字段值，仅作为"变化方向"参考，不当利润基准（仓库红线）
        "margin_rate": m.num(ts.get("gross_margin")),
        "fetched_at": dt.datetime.now().strftime("%Y-%m-%d %H:%M"),
    }


def merge_month_rows(new_rows):
    """按 (shop,month) 合并写入 shop_monthly.csv。"""
    out_dir = Path(m.DATA)
    out_dir.mkdir(parents=True, exist_ok=True)
    dst = out_dir / (MONTH_TABLE + ".csv")
    keys = {(r["shop"], r["month"]) for r in new_rows}
    kept = []
    if dst.exists():
        import csv as _csv
        for r in _csv.DictReader(io.StringIO(dst.read_text(encoding="utf-8"))):
            if (r.get("shop"), str(r.get("month", "")).strip()) in keys:
                continue
            kept.append(r)
    merged = kept + [{k: ("" if v is None else v) for k, v in r.items()} for r in new_rows]
    buf = io.StringIO()
    import csv as _csv
    w = _csv.DictWriter(buf, fieldnames=MONTH_COLS, extrasaction="ignore")
    w.writeheader()
    for r in merged:
        w.writerow(r)
    dst.write_text(buf.getvalue(), encoding="utf-8")
    return dst, len(kept), len(new_rows)


def row_from_total(shop, day, ts):
    """total_sum → shop_daily 一行（数值经 metrics 清洗；毛利/利润不落表）。"""
    def n(key):
        return m.num(ts.get(key))
    inv = ts.get("available_inventory")
    inv_total = m.num(inv.get("available_inventory")) if isinstance(inv, dict) else None
    return {
        "shop": shop, "date": day,
        "units": n("volume"), "revenue": n("amount"), "net_revenue": n("net_amount"),
        "orders": n("order_items"), "sessions": n("sessions_total"),
        "page_views": n("page_views_total"), "spend": n("spend"),
        "ad_sales": n("ad_sales_amount"), "acos": n("acos"),
        "return_rate": n("return_rate"), "fba_available": n("afn_fulfillable_quantity"),
        "available_inventory": inv_total,
        "units_yoy_ratio": n("volume_yoy_ratio"),
        "fetched_at": dt.datetime.now().strftime("%Y-%m-%d %H:%M"),
    }


def merge_rows(new_rows, drop_dates=None):
    """按 (shop,date) 合并写入 shop_daily.csv；可清除不再合法的日期快照。"""
    out_dir = Path(m.DATA)
    out_dir.mkdir(parents=True, exist_ok=True)
    dst = out_dir / (OUT_TABLE + ".csv")
    drop_dates = set(drop_dates or ())
    keys = {(r["shop"], r["date"]) for r in new_rows}
    kept = []
    if dst.exists():
        import csv as _csv
        for r in _csv.DictReader(io.StringIO(dst.read_text(encoding="utf-8"))):
            if str(r.get("date", "")).strip() in drop_dates:
                continue
            if (r.get("shop"), str(r.get("date", "")).strip()) in keys:
                continue
            kept.append(r)
    merged = kept + [{k: ("" if v is None else v) for k, v in r.items()} for r in new_rows]
    buf = io.StringIO()
    import csv as _csv
    w = _csv.DictWriter(buf, fieldnames=OUT_COLS, extrasaction="ignore")
    w.writeheader()
    for r in merged:
        w.writerow(r)
    dst.write_text(buf.getvalue(), encoding="utf-8")
    return dst, len(kept), len(new_rows)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=3, help="重拉最近 N 个完整日，不含今天（默认 3）")
    ap.add_argument("--shops", default="", help="逗号分隔的店铺组名，缺省全部")
    ap.add_argument("--selftest", action="store_true", help="不联网：用样例数据验证管道")
    ap.add_argument("--mode", default="daily", choices=["daily", "monthly"],
                    help="daily=按天重拉最近 N 个完整日；monthly=逐月拉最近 N 个完整月")
    ap.add_argument("--months", type=int, default=24,
                    help="monthly 模式拉最近 N 个完整自然月（默认 24，领星单次跨度上限 1 年故逐月调）")
    ap.add_argument("--force", action="store_true",
                    help="monthly 忽略本地缓存强制重拉；daily 近期完整日本来就会重拉")
    ap.add_argument("--allow-zero", action="store_true",
                    help="人工确认真实全零停业日后，允许店级零值落盘（默认拒绝未核验零值）")
    args = ap.parse_args()

    shops = load_shops()
    wanted = [s.strip() for s in args.shops.split(",") if s.strip()] or list(shops)
    for s in wanted:
        if s not in shops:
            sys.exit("shops.yaml 里没有店铺组 %r（可选：%s）" % (s, ", ".join(shops)))

    today = dt.date.today()
    days = recent_complete_days(today, args.days)

    if args.selftest:
        # 自检绝不写真实 data/ 目录——2026-11-04 曾把样本数据（58件/$55,747）写进
        # data/normalized/shop_daily.csv 覆盖掉多店真数据，导致预警里三家店数字完全一样。
        # 现在固定落到临时目录，跑完即删，进程环境里也不需要 MCP 凭证。
        import shutil
        import tempfile
        tmpdir = tempfile.mkdtemp(prefix="amz_fetch_selftest_")
        old_data = m.DATA
        m.DATA = tmpdir
        try:
            rows = [row_from_total(s, d, SAMPLE_TOTAL_SUM) for s in wanted for d in days]
            dst, kept, n_new = merge_rows(rows)
            # 幂等性也验一遍：同键重写应替换而不是追加
            merge_rows(rows)
            with open(dst, encoding="utf-8") as f:
                lines = sum(1 for _ in f) - 1
            assert lines == n_new, "幂等性失败：重写后行数 %d ≠ 首次 %d" % (lines, n_new)
            print("✓ [selftest] %d 行写入临时目录（幂等重写后仍 %d 行，未触碰 data/）"
                  % (n_new, lines))
        finally:
            m.DATA = old_data
            shutil.rmtree(tmpdir, ignore_errors=True)
        return

    # 凭证两条路：环境变量，或 config/mcp.local.json（GUI 客户端拿不到 shell 变量时用后者）
    import mcp_client as mc
    url, key = mc.credential("lingxing", "LINGXING_MCP_URL", "LINGXING_MCP_KEY")
    if not url or not key:
        sys.exit("缺领星凭证：任选一种——(1) export LINGXING_MCP_URL 与 LINGXING_MCP_KEY；"
                 "(2) 填 config/mcp.local.json 的 lingxing 段（见 docs/CLIENTS.md）")

    client = LingxingMCP(url, key)
    client.initialize()

    # ---- 日常校准：窗口内全部是已结束日期，每次重拉，不能用“日期存在”跳过 ----
    plan = {}
    if args.mode == "daily":
        plan = {shop: list(days) for shop in wanted}

    if args.mode == "monthly":
        months = month_range(args.months)
        rows = []
        skipped = 0
        n_new, kept = 0, 0
        for shop in wanted:
            sids = shops[shop]["sids"]
            have = set() if args.force else have_months(shop)
            shop_rows = []
            for month, s, e in months:
                if month in have:
                    skipped += 1
                    continue  # 本地已有该月，不重复拉（增量缓存）
                ts = pull_shop_month(client, sids, s, e)
                if not ts:
                    print("  · %s %s：无数据（跳过）" % (shop, month))
                    time.sleep(1.1)
                    continue
                r = row_from_month(shop, month, ts)
                rows.append(r)
                shop_rows.append(r)
                print("  · %s %s：ACOS %.1f%%，退货率 %.1f%%，销售额 %s" % (
                    shop, month,
                    (m.num(ts.get("acos")) or 0) * 100,
                    (m.num(ts.get("return_rate")) or 0) * 100,
                    ts.get("amount")))
                time.sleep(1.1)  # 领星限流 QPS=1
            # 每店拉完立刻落盘：补历史动辄上百次调用，全攒在内存里中途挂了就白跑
            if shop_rows:
                dst, kept, n = merge_month_rows(shop_rows)
                n_new += n
                print("  ✓ %s 已落盘 %d 个月（文件现有 %d 行）" % (shop, n, kept + n))
        print("✓ 本轮新增 %d 个店铺月（缓存命中跳过 %d 个）" % (n_new, skipped))
        return

    rows, n_new = [], 0
    sku_rows = m.load("sales_daily")
    for shop in wanted:
        sids = shops[shop]["sids"]
        shop_rows = []
        for day in plan.get(shop, days):
            ts = pull_shop_day(client, sids, day)
            r = row_from_total(shop, day, ts)
            validate_shop_row(r, sku_rows, allow_zero=args.allow_zero)
            rows.append(r)
            shop_rows.append(r)
            print("  · %s %s：销量 %s，销售额 %s" % (
                shop, day, ts.get("volume"), ts.get("amount")))
            time.sleep(1.1)  # 领星限流 QPS=1
        # 每店拉完立刻落盘：拉 400 天 × 3 店要上千次调用（QPS=1 近一小时），
        # 全攒在内存里中途挂了就白跑——2026-11-04 首次补历史时踩到这条。
        if shop_rows:
            dst, kept, n = merge_rows(shop_rows, drop_dates={today.isoformat()})
            n_new += n
            print("  ✓ %s 已落盘 %d 天（文件现有 %d 行）" % (shop, n, kept + n))
    print("✓ 本轮重拉校准 %d 个店铺完整日" % n_new)
    try:
        table = m.load("shop_daily")
        dates = m.table_dates(table)
        complete = [d for d in dates if d < dt.date.today().isoformat()] or dates
        m.write_fetch_status("lingxing", True, "近期完整日已重拉校准；shop_daily 最新 %s" % (dates[-1] if dates else "-"),
                             rows=len(table), min_date=dates[0] if dates else "",
                             max_date=complete[-1] if complete else "")
    except Exception:
        pass


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        try:
            table = m.load("shop_daily")
            dates = m.table_dates(table)
            complete = [d for d in dates if d < dt.date.today().isoformat()] or dates
            m.write_fetch_status("lingxing", False, str(exc)[:200], rows=len(table),
                                 min_date=dates[0] if dates else "",
                                 max_date=complete[-1] if complete else "", error=str(exc))
        except Exception:
            pass
        raise
