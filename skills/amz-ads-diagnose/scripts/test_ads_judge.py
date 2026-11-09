#!/usr/bin/env python3
"""广告诊断 judge 逻辑的单测：烧钱 / ACOS 超线 / 花费骤增。

为什么值得测：广告告警直接决定运营今天先看哪条 campaign。
- 漏掉"花了钱没出单"是真金白银在烧；
- 把"订单少导致 ACOS 虚高"当严重问题会让人瞎关广告。
所以两个方向都要钉住，特别是 MIN_CLICKS 这道闸。
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "..", "_shared"))
sys.path.insert(0, HERE)
import run as ads  # noqa: E402

ok = 0


def check(name, cond):
    assert cond, name
    print("  ✓ " + name)
    global ok
    ok += 1


def row(spend=0, sales=0, orders=0, clicks=0, acos=None, name="C1", cid="1"):
    return {"shop": "shop_a", "campaign_name": name, "campaign_id": cid,
            "spends": spend, "sales": sales, "orders": orders, "clicks": clicks,
            "acos": acos}


def one(r):
    alerts, s = ads.judge({"2026-11-03": [r]})
    return alerts


# ---------- 烧钱：花了钱没出单 ----------
a = one(row(spend=20, orders=0, clicks=10))
check("花 $20 / 10 点击 / 0 单 → critical 烧钱",
      len(a) == 1 and a[0]["level"] == "critical" and "花了" in a[0]["msg"])

a = one(row(spend=20, orders=0, clicks=5))
check("点击不足 %d 时不判烧钱（样本太小）" % ads.MIN_CLICKS, a == [])

a = one(row(spend=10, orders=0, clicks=10))
check("花费低于 $%.0f 不判" % ads.NO_ORDER_SPEND, a == [])

a = one(row(spend=20, orders=2, clicks=10, acos=0.10))
check("有单且 ACOS 低 → 不报", a == [])

# ---------- ACOS 超线（有单才看） ----------
a = one(row(spend=50, sales=160, orders=2, clicks=20, acos=0.31))
check("ACOS 31% → critical",
      any(x["level"] == "critical" and "ACOS" in x["msg"] for x in a))

a = one(row(spend=50, sales=250, orders=2, clicks=20, acos=0.20))
check("ACOS 20% → high（超过 18% 但没到 25%）",
      any(x["level"] == "high" and "ACOS" in x["msg"] for x in a))

a = one(row(spend=50, sales=500, orders=2, clicks=20, acos=0.10))
check("ACOS 10% → 不报", a == [])

# ---------- 花费骤增 ----------
alerts, s = ads.judge({
    "2026-11-03": [row(spend=20, orders=1, clicks=10, acos=0.10)],
    "2026-11-04": [row(spend=80, orders=1, clicks=30, acos=0.30)],
})
check("花费 20→80（4 倍）报 high",
      any(x["level"] == "high" and "花费" in x["msg"] for x in alerts))

alerts, s = ads.judge({
    "2026-11-03": [row(spend=20, orders=1, clicks=10, acos=0.10)],
    "2026-11-04": [row(spend=25, orders=1, clicks=12, acos=0.10)],
})
check("花费只涨 25% 不报骤增", alerts == [])

# ---------- 汇总口径 ----------
alerts, s = ads.judge({"2026-11-04": [row(spend=30, sales=100, orders=2, clicks=20, acos=0.30)]})
check("汇总算出 TACOS = 花费/广告销售额", abs(s["tacos"] - 0.30) < 1e-9)
check("汇总带日期与 campaign 数", s["date"] == "2026-11-04" and s["campaigns"] == 1)

# ---------- 去重 ----------
same = [row(spend=20, orders=0, clicks=10, name="C1", cid="1"),
        row(spend=20, orders=0, clicks=10, name="C1", cid="1")]
a = one(same[0])
check("同一 campaign 只报一次", len(a) == 1)

print("\n全部通过：%d 项断言" % ok)
