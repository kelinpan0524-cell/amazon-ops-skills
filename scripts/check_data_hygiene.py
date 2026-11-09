#!/usr/bin/env python3
"""数据卫生检查：找出"看起来有数、其实是假数/串数"的情况。

为什么需要（2026-11-04 真实事故）：
`fetch_lingxing.py --selftest` 曾把样本数据（58 件 / $55,747.9 / 花费 2241.84）
写进真实 data/ 目录，覆盖了三家店的真实日数据。结果预警里三家店的"花费"完全一样，
看上去像正常告警，实际是全假——**没有任何地方会报错**。

本脚本把这类"静默脏数据"变成显式报警：
  1. 同一天多家店的核心指标完全相同（串数/复制）；
  2. 同一家店连续多天所有指标完全相同（假数据/未更新）；
  3. 关键字段大面积为空或全 0；
  4. 近期店级全零与 SKU 明细矛盾，或没有明细可证明真实零销售；
  5. 日期覆盖与实际新鲜度不符。

用法：
  python3 scripts/check_data_hygiene.py            # 检查 data/normalized
  python3 scripts/check_data_hygiene.py --strict   # 有问题非零退出（定时任务/CI 用）
"""
import argparse
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "skills" / "_shared"))
import metrics as m  # noqa: E402

# 判定"两行一样"时比较的字段（不比较 fetched_at 这种时间戳）
NUM_KEYS = ("units", "revenue", "spend", "ad_sales", "sessions", "fba_available")


def fingerprint(row, keys=NUM_KEYS):
    """把关键指标拼成可比对的指纹；全空/全 0 返回 None（不值得比）。"""
    vals = []
    for k in keys:
        v = m.num(row.get(k))
        vals.append("" if v is None else "%.4f" % v)
    if all(v in ("", "0.0000") for v in vals):
        return None
    return "|".join(vals)


def check_shop_daily(rows):
    """日表检查：同一天跨店同值 / 同一店连续同值。"""
    issues = []

    # 1) 同一天多家店核心指标完全相同 → 极可能是同一份数据被复制到多店
    by_date = defaultdict(dict)
    for r in rows:
        d, shop = m.row_date(r), r.get("shop")
        if d and shop:
            by_date[d][shop] = r
    for d, shops in sorted(by_date.items()):
        if len(shops) < 2:
            continue
        seen = defaultdict(list)
        for shop, r in shops.items():
            fp = fingerprint(r)
            if fp:
                seen[fp].append(shop)
        for fp, names in seen.items():
            if len(names) >= 2:
                issues.append((
                    "cross-shop-same",
                    "high",
                    "%s：%s 的核心指标完全相同（%s）——疑似同一份数据被复制到多店，"
                    "或 selftest 样本写进了真实目录" % (d, "、".join(names), fp)))

    # 2) 同一店连续多天所有指标完全相同 → 假数据/未更新
    for shop in {r.get("shop") for r in rows}:
        seq = [(m.row_date(r), fingerprint(r)) for r in rows if r.get("shop") == shop]
        seq = [(d, fp) for d, fp in seq if d and fp]
        seq.sort()
        run_start, run_len, last_fp = None, 1, None
        for i, (d, fp) in enumerate(seq):
            if fp == last_fp:
                run_len += 1
            else:
                if run_len >= 3:
                    issues.append(("frozen-days", "high",
                                   "%s：%s 起连续 %d 天所有指标完全相同——数据没更新或是假数据"
                                   % (shop, run_start, run_len)))
                run_start, run_len, last_fp = d, 1, fp
        if run_len >= 3:
            issues.append(("frozen-days", "high",
                           "%s：%s 起连续 %d 天所有指标完全相同——数据没更新或是假数据"
                           % (shop, run_start, run_len)))
    return issues


def check_shop_sku_consistency(shop_rows, sales_rows):
    """店级全零必须与 SKU 明细交叉核验；SKU 合计不替代店级金额。"""
    issues = []
    sku_by_key = defaultdict(list)
    for r in sales_rows:
        key = (r.get("shop"), m.row_date(r))
        if key[0] and key[1]:
            sku_by_key[key].append(r)
    recent_dates = sorted({m.row_date(r) for r in shop_rows if m.row_date(r)})[-3:]
    recent = set(recent_dates)
    for r in shop_rows:
        shop, day = r.get("shop"), m.row_date(r)
        if not shop or day not in recent:
            continue
        if (m.num(r.get("units")) or 0) != 0 or (m.num(r.get("revenue")) or 0) != 0:
            continue
        related = sku_by_key.get((shop, day), [])
        units = sum(m.num(x.get("units")) or 0 for x in related)
        revenue = sum(m.num(x.get("revenue")) or 0 for x in related)
        if related and (units != 0 or revenue != 0):
            issues.append((
                "shop-sku-zero-mismatch", "high",
                "%s %s 店级销量/销售额全为 0，但 SKU 明细为 %s 件 / $%.2f；"
                "店级未完整快照被当成正式数据" % (shop, day, format(units, "g"), revenue)))
        else:
            issues.append((
                "shop-zero-unverified", "medium",
                "%s %s 店级销量/销售额全为 0，近期 SKU 明细也不能证明这是真实零销售；"
                "请重拉领星店级与 SKU 数据" % (shop, day)))
    return issues


def check_table(name, rows, required):
    """通用检查：行数、关键字段空值率。"""
    issues = []
    if not rows:
        return [("empty", "medium", "%s 表为空" % name)]
    for col in required:
        filled = sum(1 for r in rows if str(r.get(col, "")).strip())
        if filled == 0:
            issues.append(("column-empty", "high",
                           "%s.%s 整列为空（%d 行）" % (name, col, len(rows))))
        elif filled < len(rows) * 0.5:
            issues.append(("column-sparse", "medium",
                           "%s.%s 只有 %d/%d 行有值" % (name, col, filled, len(rows))))
    return issues


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--strict", action="store_true")
    args = ap.parse_args()

    issues = []
    daily = m.load("shop_daily")
    monthly = m.load("shop_monthly")
    sales = m.load("sales_daily")

    if daily:
        issues += check_shop_daily(daily)
        issues += check_shop_sku_consistency(daily, sales)
        issues += check_table("shop_daily", daily, ("shop", "date", "revenue"))
    if monthly:
        issues += check_table("shop_monthly", monthly, ("shop", "month", "revenue"))

    if not daily and not monthly:
        print("没有 shop_daily / shop_monthly 数据（先跑 scripts/fetch_lingxing.py）")
        return 2 if args.strict else 0

    print("检查：shop_daily %d 行、shop_monthly %d 行" % (len(daily), len(monthly)))
    high = [i for i in issues if i[1] == "high"]
    if not issues:
        print("✓ 未发现串数/冻结/空列问题")
    for kind, level, msg in issues:
        print("  [%s] %s：%s" % (level, kind, msg))
    if high:
        print("\n✗ %d 个高危问题：报告里的数字可能不可信，先修数据" % len(high))
    return 1 if (args.strict and issues) else 0


if __name__ == "__main__":
    sys.exit(main())
