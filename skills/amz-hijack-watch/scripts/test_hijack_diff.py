#!/usr/bin/env python3
"""跟卖监控 diff 逻辑的单测：卖家数变化 × 价格变化 → 告警级别。

为什么值得测：跟卖告警会直接推给运营，误报会让人对预警系统失去信任
（"狼来了"效应），漏报则真的丢购物车。所以两个方向都要钉住：
- 卖家 1 → 2 必须报 critical（这是真的有人进来）
- 价格跌但只有 1 个卖家时必须降级到 medium（可能只是我们自己促销）
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "..", "_shared"))
sys.path.insert(0, HERE)
import run as hw  # noqa: E402

ok = 0


def check(name, cond):
    global ok
    assert cond, name
    print("  ✓ " + name)
    ok += 1


def snap(sellers=1, price=100.0, price_min=None):
    return {"sellers_last": sellers, "sellers": sellers,
            "price": price, "price_min": price_min if price_min is not None else price}


def two(before, after):
    return hw.diff({"date": "2026-11-03", "items": {"B0AAAAAAAA": before}},
                   {"date": "2026-11-04", "items": {"B0AAAAAAAA": after}})


# ---------- 卖家数变化 ----------
ch = two(snap(1), snap(3))
check("卖家 1→3 报 critical「出现跟卖」",
      len(ch) == 1 and ch[0]["level"] == "critical" and ch[0]["kind"] == "出现跟卖")

ch = two(snap(2), snap(4))
check("卖家 2→4 报 high「跟卖扩散」",
      len(ch) == 1 and ch[0]["level"] == "high" and ch[0]["kind"] == "跟卖扩散")

ch = two(snap(3), snap(1))
check("卖家 3→1 报 info「跟卖退出」",
      len(ch) == 1 and ch[0]["level"] == "info" and ch[0]["kind"] == "跟卖退出")

ch = two(snap(2), snap(2))
check("卖家数不变不报", ch == [])

# ---------- 价格变化 ----------
ch = two(snap(3, 100.0), snap(3, 90.0))
check("有跟卖时跌 10% → critical（压价抢购物车）",
      any(c["kind"] == "价格下跌" and c["level"] == "critical" for c in ch))

ch = two(snap(1, 100.0), snap(1, 90.0))
check("只有 1 家时跌 10% → high（不是 critical，可能自己促销）",
      any(c["kind"] == "价格下跌" and c["level"] == "high" for c in ch))
check("只有 1 家时跌 10% 不报 critical",
      not any(c["level"] == "critical" for c in ch))

ch = two(snap(1, 100.0), snap(1, 93.0))
check("只有 1 家时跌 7%（未到 10%）→ medium",
      any(c["kind"] == "价格下跌" and c["level"] == "medium" for c in ch))

# 涨价
ch = two(snap(1, 100.0), snap(1, 115.0))
check("涨价 15% → high（要看转化有没有掉）",
      any(c["kind"] == "价格上涨" and c["level"] == "high" for c in ch))

# 数据异常（抓取读错）
ch = two(snap(1, 100.0), snap(1, 20.0))
check("跌 80% 当成数据异常而不是价格信号",
      any(c["kind"] == "数据异常" for c in ch)
      and not any(c["kind"] == "价格下跌" for c in ch))

ch = two(snap(1, 100.0), snap(1, 96.0))
check("跌 4%（低于 5% 阈值）不报", ch == [])

ch = two(snap(1, 100.0), snap(1, 95.0))
check("跌 5%（正好到阈值）要报",
      any(c["kind"] == "价格下跌" for c in ch))

# ---------- 组合与排序 ----------
ch = two(snap(1, 100.0), snap(3, 90.0))
check("同时出现跟卖与跌价，critical 排前面",
      len(ch) >= 2 and ch[0]["level"] == "critical"
      and all(c["level"] == "critical" for c in ch if ch.index(c) == 0))

# ---------- 边界 ----------
ch = two(snap(1), snap(1, price=None))
check("缺价格时不报价格变化（不把缺数当 0）", ch == [])

ch = two(snap(1, price=None), snap(1, 90.0))
check("上次缺价格时不报价格变化", ch == [])

ch = hw.diff({"date": "2026-11-03", "items": {}},
             {"date": "2026-11-04", "items": {"B0AAAAAAAA": snap(5)}})
check("首次出现的 ASIN 不报变化（没有基准）", ch == [])

# ---------- 名单解析 ----------
asins = hw.parse_asins("| B0D62SYW8S | shop_a | 控制臂 |\n| B0ABC12345 | shop_b | 衬套 |\n")
check("从 md 表格抽 ASIN", [a["asin"] for a in asins] == ["B0D62SYW8S", "B0ABC12345"])
check("重复 ASIN 去重",
      len(hw.parse_asins("B0D62SYW8S\nB0D62SYW8S\n")) == 1)

print("\n全部通过：%d 项断言" % ok)
