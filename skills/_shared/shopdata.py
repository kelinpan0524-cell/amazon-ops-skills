#!/usr/bin/env python3
"""店铺日数据的共享读取层：四个报告技能（日报/总览/周月复盘/预警）共用一份。

为什么单独一层：这些脚本原先各写一套 `val()/ratio()/读 shop_daily/取最新完整日`，
口径细节（今天数据未齐怎么退、多店日期不同步怎么取）很容易各写各的、慢慢走偏。
集中到这里，改一次全一致。

约定：
  - 所有数值经 metrics.num() 读取（缺数返回 None，绝不冒充 0）；
  - 「最新完整日」= 表内最近一个不是今天的日期（领星当天数据次日才齐）；
  - 各店可能不同步，按店各取各的最新完整日；
  - 区间汇总只统计表内真实存在的日期，并返回覆盖天数供上层判断可比性。
"""
from __future__ import annotations

import datetime as dt
from pathlib import Path

import metrics as m

VAL_KEYS = ("units", "revenue", "net_revenue", "orders", "sessions",
            "page_views", "spend", "ad_sales")


def val(row: dict, key: str) -> float | None:
    """读一个数值字段（缺数返回 None）。"""
    return m.num(row.get(key)) if row else None


def ratio(cur: float | None, old: float | None) -> float | None:
    """环比/同比：old 为 0 或 None 时返回 None（不做除零，也不编 0%）。"""
    if cur is None or old in (None, 0):
        return None
    return (cur - old) / old


def fmt_delta(r: float | None, suffix: str = "%") -> str:
    """环比展示：+12% / -8% / 无基线。"""
    return "无基线" if r is None else "%+.0f%s" % (r * 100, suffix)


def load_by_shop(table: str = "shop_daily") -> dict:
    """读表并按店铺分组：{shop: {iso_date: row}}，日期已归一。"""
    out: dict[str, dict[str, dict]] = {}
    for r in m.load(table):
        shop, d = r.get("shop"), m.row_date(r)
        if shop and d:
            out.setdefault(shop, {})[d] = r
    return out


def latest_by_shop(by_shop: dict, today: str | None = None) -> dict:
    """每店最近一个「非今天」的完整日：{shop: (date, row)}。"""
    today = today or dt.date.today().isoformat()
    picked = {}
    for shop, by_date in by_shop.items():
        days = sorted(by_date)
        full = [d for d in days if d != today] or days
        if full:
            picked[shop] = (full[-1], by_date[full[-1]])
    return picked


def previous_by_shop(by_shop: dict, picked: dict) -> dict:
    """每店在 picked 日期之前的最近一行：{shop: row}（用于环比）。"""
    out = {}
    for shop, (d, _) in picked.items():
        earlier = [dd for dd in sorted(by_shop.get(shop, {})) if dd < d]
        if earlier:
            out[shop] = by_shop[shop][earlier[-1]]
    return out


def aggregate(by_shop: dict, start: str, end: str, shops=None, sum_keys=None) -> tuple:
    """区间汇总（含边界）。返回 (per_shop, total, covered_days)。

    covered_days 是区间内「表里真有数据」的天数（不是日历天数），
    上层用它判断环比/同比是否可比（覆盖不足 70% 就是不可比）。
    """
    sum_keys = sum_keys or VAL_KEYS
    per_shop, days = {}, set()
    for shop, by_date in by_shop.items():
        if shops and shop not in shops:
            continue
        acc = {k: 0.0 for k in sum_keys}
        hit = False
        for d, row in by_date.items():
            if start <= d <= end:
                hit = True
                days.add(d)
                for k in sum_keys:
                    acc[k] += val(row, k) or 0.0
        if hit:
            per_shop[shop] = acc
    total = {k: sum(v[k] for v in per_shop.values()) for k in sum_keys}
    return per_shop, total, len(days)


def is_comparable(covered: int, expected: int, min_ratio: float = 0.7) -> bool:
    """覆盖天数达到期望的 70% 才算可比（否则环比会被残缺数据拉偏）。"""
    return expected > 0 and covered >= expected * min_ratio


def week_bounds(anchor: str | None = None) -> tuple:
    """ISO 周（周一起算）→ (本周起, 本周止, 上期起, 上期止, 去年同期起, 去年同期止)。

    不传 anchor 时取「上一个完整自然周」（本周未过完，不拿它比）。
    """
    if anchor:
        y, w = anchor.split("-W")
        start = dt.date.fromisocalendar(int(y), int(w), 1)
    else:
        today = dt.date.today()
        start = today - dt.timedelta(days=today.weekday() + 7)
    end = start + dt.timedelta(days=6)
    prev_start = start - dt.timedelta(days=7)
    # 去年同期 = 去年「同一个 ISO 周号」的周一（不是简单减 365 天——
    # 那样会落到周日或跨周，同比窗口错位一两天，等于拿错区间比）
    iso_y, iso_w, _ = start.isocalendar()
    try:
        yoy_start = dt.date.fromisocalendar(iso_y - 1, iso_w, 1)
    except ValueError:  # 去年没有第 53 周（平年）
        yoy_start = dt.date.fromisocalendar(iso_y - 1, 52, 1) + dt.timedelta(days=7)
    return start, end, prev_start, prev_start + dt.timedelta(days=6), \
        yoy_start, yoy_start + dt.timedelta(days=6)


def month_bounds(anchor: str | None = None) -> tuple:
    """自然月 → (本月起, 本月止, 上期起, 上期止, 去年同期起, 去年同期止)。

    不传 anchor 时取「上一个完整自然月」。
    """
    if anchor:
        y, mo = int(anchor[:4]), int(anchor[5:7])
        start = dt.date(y, mo, 1)
    else:
        first = dt.date.today().replace(day=1)
        start = (first - dt.timedelta(days=1)).replace(day=1)
    nxt = (start.replace(day=28) + dt.timedelta(days=4)).replace(day=1)
    end = nxt - dt.timedelta(days=1)
    prev_start = (start - dt.timedelta(days=1)).replace(day=1)
    prev_end = start - dt.timedelta(days=1)
    yoy_start = start.replace(year=start.year - 1)
    yoy_end = (yoy_start.replace(day=28) + dt.timedelta(days=4)).replace(day=1) - dt.timedelta(days=1)
    return start, end, prev_start, prev_end, yoy_start, yoy_end


def load_shops_config(root: Path) -> dict:
    """读 config/shops.json 的 shops 段（店铺组 → sids/display/operator）。"""
    import json
    cfg = json.loads((root / "config" / "shops.json").read_text(encoding="utf-8"))
    shops = cfg.get("shops") or {}
    if not shops:
        raise SystemExit("config/shops.json 里没有店铺组")
    return shops
