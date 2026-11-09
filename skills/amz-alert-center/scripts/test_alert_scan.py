#!/usr/bin/env python3
"""alert-center 规则引擎的单测：8 条规则 × 级别过滤 × 阈值边界。

为什么值得测：`yoy-drop` 曾经"配置里有、文档里有、代码里没有"——靠人工查漏才发现。
规则引擎是推送决策的核心，必须用会红的测试钉住。
"""
import datetime as dt
import os
import sys
from pathlib import Path
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "..", "_shared"))
sys.path.insert(0, HERE)
import run as ac  # noqa: E402

ok = 0
TODAY = dt.date.today().isoformat()


def check(name, cond):
    global ok
    assert cond, name
    print("  ✓ " + name)
    ok += 1


def row(units=10, revenue=1000.0, spend=10.0, orders=10.0, acos=0.2,
        fba=100.0, ret=0.02):
    return {"units": str(units), "revenue": str(revenue), "spend": str(spend),
            "orders": str(orders), "acos": str(acos), "fba_available": str(fba),
            "return_rate": str(ret), "sessions": "100", "ad_sales": "500",
            "net_revenue": str(revenue), "page_views": "120", "units_yoy_ratio": "0.1"}


SHOPS = {"shop_a": {"display": "锦力", "sids": "1"}}


def run_case(days, min_level="low", shop="shop_a", fetch_status=None):
    """days: [(date, row), ...] 构造 idx/latest 后跑 scan。

    load_fetch_status 会读本机 data/logs/fetch_status.json——那是运行状态，不是测试输入。
    不屏蔽它，机器上先跑过一次拉数（尤其失败过）就会把「数据断供」测成「拉取失败」，
    同事按文档先 fetch 再 selftest 会莫名其妙红。测试必须自带输入、不读机器状态。
    """
    idx = {shop: dict(days)}
    latest = {shop: max(d for d, _ in days)}
    with mock.patch.object(ac, "load_fetch_status", return_value=fetch_status or {}):
        return ac.scan(idx, latest, SHOPS, ac.load_rules(),
                       only_shop=None, min_level=min_level)


# ---------- 规则表完整性 ----------
rules = ac.load_rules()
ids = {r["id"] for r in rules}
check("规则表至少 10 条（ACOS 两档 + 退货率两档 + 目标落后）", len(rules) >= 10)
check("yoy-drop 不在启用列表里", "yoy-drop" not in ids)
check("每条规则都有 why 与 action（报告里要展示）",
      all(r.get("why") and r.get("action") for r in rules))

# 配了开关但代码没实现的规则 = 死配置（yoy-drop 就曾这样混过去）。
# 断言每个启用的 id 都在 run.py 的 scan() 里出现过，而不是钉死规则总数。
_src = Path(ac.__file__).read_text(encoding="utf-8")
_dead = [r["id"] for r in rules
         if r.get("enabled") and ('"%s"' % r["id"]) not in _src]
check("每条启用规则都在 scan() 里有实现（无死配置）", not _dead)

# ---------- 销售骤降 ----------
d = (dt.date.today() - dt.timedelta(days=1)).isoformat()
alerts = run_case([(d, row(revenue=1000)), ("2026-01-02", row(revenue=500))])
# 注意：日期间隔很大，先只验"跌 50% 触发 high"
alerts = run_case([("2026-01-01", row(revenue=1000)), ("2026-01-02", row(revenue=600))])
check("跌 40% 触发 sales-drop（阈值 30%）",
      any(a["rule"] == "销售额骤降" and a["level"] == "high" for a in alerts))
alerts = run_case([("2026-01-01", row(revenue=1000)), ("2026-01-02", row(revenue=800))])
check("跌 20% 不触发（阈值 30%）",
      not any(a["rule"] == "销售额骤降" for a in alerts))

# ---------- ACOS ----------
alerts = run_case([("2026-01-01", row(acos=0.20))])
check("ACOS 20% 触发 medium（阈值 18%，业务定调）",
      any(a["rule"] == "ACOS 偏高" and a["level"] == "medium" for a in alerts))
alerts = run_case([("2026-01-01", row(acos=0.15))])
check("ACOS 15% 不触发（低于 18% 常态线）", not any("ACOS" in a["rule"] for a in alerts))
alerts = run_case([("2026-01-01", row(acos=0.30))])
check("ACOS 30% 触发 high 档（阈值 25%）且不重复报 medium 档",
      any(a["rule"] == "ACOS 严重偏高" and a["level"] == "high" for a in alerts)
      and not any(a["rule"] == "ACOS 偏高" for a in alerts))

# ---------- 有花费无单 ----------
alerts = run_case([("2026-01-01", row(spend=80, orders=0))])
check("花费 80 且 0 单 → 触发",
      any(a["rule"] == "有花费无订单" for a in alerts))
alerts = run_case([("2026-01-01", row(spend=30, orders=0))])
check("花费 30 且 0 单 → 不触发（阈值 50）",
      not any(a["rule"] == "有花费无订单" for a in alerts))

# ---------- 断货 ----------
alerts = run_case([("2026-01-01", row(units=10, fba=0))])
check("FBA 可售 0 且有销量 → 已断货 critical",
      any(a["rule"] == "已断货" and a["level"] == "critical" for a in alerts))
alerts = run_case([("2026-01-01", row(units=10, fba=20))])
check("FBA 可售 20（约 2 天）→ 断货风险",
      any(a["rule"] == "断货风险" for a in alerts))

# ---------- 退货 ----------
alerts = run_case([("2026-01-01", row(ret=0.085))])
check("退货率 8.5% → 触发接近收费线（阈值 8%）",
      any(a["rule"] == "退货率接近收费线" for a in alerts))
alerts = run_case([("2026-01-01", row(ret=0.05))])
check("退货率 5% → 不触发", not any("退货率" in a["rule"] for a in alerts))
# 月线 9.1%：需要近 30 天退货件数/发货件数 > 9.1% 且发货 ≥25 件
month = [((dt.date(2026, 1, 1) + dt.timedelta(days=i)).isoformat(),
          dict(row(units=10, ret=0.10), refund_units="2")) for i in range(30)]
alerts = run_case(month)
check("近 30 天退货率 20%（2/10）→ 触发官方收费线 critical",
      any(a["rule"] == "退货率超官方收费线" and a["level"] == "high" for a in alerts))

# ---------- 周趋势 ----------
week = [((dt.date(2026, 1, 1) + dt.timedelta(days=i)).isoformat(),
         row(revenue=1000 if i < 7 else 600)) for i in range(14)]
alerts = run_case(week)
check("近 7 天较前 7 天跌 40% → 周趋势下滑",
      any(a["rule"] == "周趋势下滑" for a in alerts))

# ---------- 数据断供 ----------
alerts = run_case([("2025-01-01", row())])   # 很久以前
check("数据停在一年前 → 数据断供 high",
      any(a["rule"] == "数据断供" and a["level"] == "high" for a in alerts))
# 同一批数据，但本机记录过拉取失败：应当报「拉取失败」，不能混成「断供」
alerts = run_case([("2025-01-01", row())],
                  fetch_status={"lingxing": {"status": "failed", "consecutive_failures": 2,
                                             "error": "MCP Key 无效"}})
check("拉取失败优先于断供（两条口径不混）",
      any(a["rule"] == "数据拉取失败" for a in alerts)
      and not any(a["rule"] == "数据断供" for a in alerts))

# ---------- 级别过滤 ----------
many = [("2026-01-01", row(acos=0.40, ret=0.12))]  # 两条 medium
high_only = ac.scan({"shop_a": dict(many)}, {"shop_a": "2026-01-01"},
                    SHOPS, rules, None, min_level="high")
check("min_level=high 只留 high 及以上（medium 被滤掉）",
      all(a["level"] in ("critical", "high") for a in high_only)
      and not any(a["level"] == "medium" for a in high_only))
check("min_level=low 保留 medium",
      len(ac.scan({"shop_a": dict(many)}, {"shop_a": "2026-01-01"},
                  SHOPS, rules, None, min_level="low")) >= 2)

# ---------- 规则可关闭 ----------
off = [dict(r, enabled=False) if r["id"] == "acos-high" else r for r in rules]
got = ac.scan({"shop_a": {"2026-01-01": row(acos=0.40)}}, {"shop_a": "2026-01-01"},
              SHOPS, off, None, min_level="low")
check("规则 enabled=false 后不再触发", not any(a["rule"] == "ACOS 偏高" for a in got))

# ---------- 排序 ----------
mixed = [("2026-01-01", row(acos=0.40, ret=0.12)), ("2026-01-02", row(fba=0, units=10))]
ordered = ac.scan({"shop_a": dict(mixed)}, {"shop_a": "2026-01-02"},
                  SHOPS, rules, None, min_level="low")
check("critical 排在 medium 之前",
      ordered[0]["level"] == "critical")

print("\n全部通过：%d 项断言" % ok)
