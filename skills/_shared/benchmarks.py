#!/usr/bin/env python3
"""基准与目标：报告里「当前值 vs 历史基准 vs 目标」的唯一取数处。

三类数分开，不许混：
  - **baseline 历史基准**：从 shop_monthly 算（P50 中位、P75），反映"我们平时什么水平"
  - **target 目标**：`config/targets.json` 里人填的（想做到多少）
  - **ceiling 红线**：外部硬指标或业务定的报警线（超了算异常）

为什么单独一层：三个报告（店日报/公司总览/周月复盘）都要显示对标，
各写一遍会出现"A 报告基准是 30 天均值、B 报告基准是 90 天均值"这种数字打架。

约定：
  - 目标未设定时返回 None，调用方显示"未设定"，**绝不用基准冒充目标**；
  - 历史不足（<6 个月）时基准返回 None 并标 `baseline_ready=False`。
"""
from __future__ import annotations

import json
from pathlib import Path

import metrics as m

ROOT = Path(__file__).resolve().parent.parent.parent
TARGETS = ROOT / "config" / "targets.json"
MIN_MONTHS_FOR_BASELINE = 6


def load_targets() -> dict:
    """读 config/targets.json；文件缺失或损坏时返回空 dict（调用方按"未设定"处理）。"""
    try:
        return json.loads(TARGETS.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def target_for(metric: str, shop: str | None = None, targets: dict | None = None):
    """取某指标的目标值：店铺覆盖 > 公司级 > None（未设定）。"""
    t = targets if targets is not None else load_targets()
    if shop:
        override = (t.get("shops") or {}).get(shop) or {}
        if metric in override and override[metric] is not None:
            return override[metric]
    return (t.get("company") or {}).get(metric)


def ceiling_for(metric: str, shop: str | None = None, targets: dict | None = None):
    """取红线值（如 acos_ceiling / return_rate_ceiling）。"""
    return target_for(metric, shop, targets)


def pct(vals, q):
    """分位数（线性插值）。空返回 None。"""
    if not vals:
        return None
    s = sorted(vals)
    if len(s) == 1:
        return s[0]
    pos = (len(s) - 1) * q
    lo, hi = int(pos), min(int(pos) + 1, len(s) - 1)
    return s[lo] + (s[hi] - s[lo]) * (pos - lo)


def history_baseline(shop: str | None = None, months: int = 12) -> dict:
    """从 shop_monthly 算历史基准。

    返回 {"acos": {"p50","p75","n"}, "return_rate": {...}, "tacos": {...},
          "months_covered": n, "baseline_ready": bool}
    只统计有销售额的月份（新店零销月会把基准拉低）。
    """
    rows = [r for r in m.load("shop_monthly")
            if shop is None or r.get("shop") == shop]
    rows = [r for r in rows if (m.num(r.get("revenue")) or 0) > 0]
    # 按「不同月份」截取最近 N 个月——不能直接 rows[-months:]：
    # 多店混合的列表里，最后 12 行大约只有 4 个月（3 店 × 4），会把基准算窄。
    if months:
        all_months = sorted({str(r.get("month", "")).strip() for r in rows if r.get("month")})
        keep = set(all_months[-months:])
        rows = [r for r in rows if str(r.get("month", "")).strip() in keep]

    acos = [m.num(r.get("acos")) for r in rows]
    acos = [v for v in acos if v is not None]
    ret = [m.num(r.get("return_rate")) for r in rows]
    ret = [v for v in ret if v is not None]
    tacos = []
    for r in rows:
        rev, spend = m.num(r.get("revenue")), m.num(r.get("spend"))
        if rev:
            tacos.append((spend or 0) / rev)

    covered = len({str(r.get("month", "")).strip() for r in rows if r.get("month")})
    return {
        "acos": {"p50": pct(acos, 0.50), "p75": pct(acos, 0.75), "n": len(acos)},
        "return_rate": {"p50": pct(ret, 0.50), "p75": pct(ret, 0.75), "n": len(ret)},
        "tacos": {"p50": pct(tacos, 0.50), "p75": pct(tacos, 0.75), "n": len(tacos)},
        "months_covered": covered,
        "baseline_ready": covered >= MIN_MONTHS_FOR_BASELINE,
    }


def kpi_note(metric: str, shop: str | None = None, baseline: dict | None = None,
             targets: dict | None = None) -> str:
    """拼出 KPI 卡下方的对照说明，如「基准 14.7% · 目标 15% · 红线 18%」。

    没有的信息就不写，不占位不猜。
    """
    parts = []
    b = baseline or {}
    key = {"acos": "acos", "return_rate": "return_rate", "tacos": "tacos"}.get(metric)
    if key and b.get("baseline_ready"):
        p50 = (b.get(key) or {}).get("p50")
        if p50 is not None:
            parts.append("基准 %s" % _fmt_pct(p50))
    tgt = target_for(metric + "_target" if not metric.endswith("_target") else metric, shop, targets)
    if tgt is not None:
        parts.append("目标 %s" % _fmt_pct(tgt))
    ceil = target_for(metric + "_ceiling" if not metric.endswith("_ceiling") else metric, shop, targets)
    if ceil is not None and metric in ("return_rate", "acos"):
        parts.append("红线 %s" % _fmt_pct(ceil))
    return " · ".join(parts) if parts else "未设定基准/目标"


# ---------- 销售目标达成（全链路 USD，不做任何币种换算） ----------

def revenue_targets(targets: dict | None = None) -> dict:
    """返回 {"year_usd","month_usd","ready"}。

    金额口径（2026-11-04 起用户确认）：领星按 USD 折算返回，目标也以 USD 存，
    全仓库不做 USD→USD 换算；报告/多维表格/群卡片一律显示美金。
    未配置年目标时 ready=False，调用方显示"目标未设定"，不编数。
    """
    t = targets if targets is not None else load_targets()
    c = t.get("company") or {}
    year_usd = c.get("annual_revenue_target_usd")
    if not year_usd:
        return {"ready": False}
    return {"ready": True,
            "year_usd": float(year_usd), "month_usd": float(year_usd) / 12}


def shop_monthly_target_usd(shop: str, targets: dict | None = None) -> float | None:
    """某店月目标（USD）。优先 shops.<店>.monthly_target_usd，缺省回落公司月目标。

    店目标是按各店历史销售占比拆出来的估算口径（不是逐店下达的指标），
    来历见 config/targets.json 的 _comment 与 docs 第十章。
    """
    t = targets if targets is not None else load_targets()
    rt = revenue_targets(t)
    if not rt.get("ready"):
        return None
    usd = ((t.get("shops") or {}).get(shop) or {}).get("monthly_target_usd")
    if not usd:
        return rt["month_usd"]
    return float(usd)


def month_progress_ratio(shop: str, mtd_revenue_usd: float, as_of_day: str,
                         targets: dict | None = None) -> dict | None:
    """当月「已卖出进度 ÷ 已过去时间」——判断月度目标是否掉队。

    直接拿「月累计达成%」在月初看会误判：11 月 4 号才过 13% 的时间，
    达成率当然也低。要看的是**达成率 ÷ 时间进度**：
      1.0 = 刚好按进度走；<0.8 = 落后；<0.6 = 严重落后。
    返回 {"pct","tprog","ratio","mtd","target_usd","days_left"} 或 None。
    """
    import calendar
    tgt = shop_monthly_target_usd(shop, targets)
    if not tgt:
        return None
    mon = as_of_day[:7]
    y, mo = int(mon[:4]), int(mon[5:7])
    mdays = calendar.monthrange(y, mo)[1]
    day = int(as_of_day[8:10])
    tprog = day / mdays
    pct = (mtd_revenue_usd or 0) / tgt
    return {"pct": pct, "tprog": tprog, "mdays": mdays, "day": day,
            "ratio": (pct / tprog) if tprog else 1.0,
            "mtd": mtd_revenue_usd or 0, "target_usd": tgt,
            "days_left": mdays - day}


def ytd_revenue(year: str | None = None) -> dict:
    """本年度累计销售额 USD（从 shop_monthly 汇总）。返回 {"total","months","by_month","year"}。"""
    import datetime as _dt
    y = year or str(_dt.date.today().year)
    by_month = {}
    for r in m.load("shop_monthly"):
        mon = str(r.get("month", "")).strip()
        if mon.startswith(y + "-"):
            by_month[mon] = by_month.get(mon, 0.0) + (m.num(r.get("revenue")) or 0.0)
    return {"year": y, "total": sum(by_month.values()), "months": len(by_month),
            "by_month": by_month}


def revenue_progress(targets: dict | None = None, year: str | None = None) -> dict:
    """年度进度：实际 vs 目标 vs 时间进度，并给出"剩余月份需要多少"（全 USD）。

    返回 {"ready","year","actual_usd","target_usd","month_target_usd",
          "pct","time_pct","months_done","months_left","need_per_month_usd","on_track"}
    """
    tg = revenue_targets(targets)
    ytd = ytd_revenue(year)
    if not tg.get("ready"):
        return {"ready": False, "year": ytd["year"], "actual_usd": ytd["total"],
                "months_done": ytd["months"]}
    months_done = max(ytd["months"], 1)
    months_left = max(12 - months_done, 0)
    remain = max(tg["year_usd"] - ytd["total"], 0)
    pct = ytd["total"] / tg["year_usd"] if tg["year_usd"] else None
    time_pct = months_done / 12.0
    return {
        "ready": True, "year": ytd["year"],
        "actual_usd": ytd["total"],
        "target_usd": tg["year_usd"],
        "month_target_usd": tg["month_usd"],
        "pct": pct, "time_pct": time_pct,
        "months_done": months_done, "months_left": months_left,
        "need_per_month_usd": (remain / months_left) if months_left else None,
        "on_track": (pct is not None and pct >= time_pct),
        "by_month": ytd["by_month"],
    }


def _fmt_pct(v) -> str:
    try:
        return "%.1f%%" % (float(v) * 100)
    except (TypeError, ValueError):
        return str(v)
