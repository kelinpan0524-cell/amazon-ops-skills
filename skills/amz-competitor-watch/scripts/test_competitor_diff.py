#!/usr/bin/env python3
"""competitor-watch 的 diff/parse 单测。

为什么值得测：`PRICE_UP_ALERT` 曾经是死常量（涨跌都走降价阈值）、`SELLER_ALERT`
声明了但没实现、SKILL.md 承诺"变化最大置顶"却没排序。这些都不会报错，只能靠断言钉住。
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "..", "_shared"))
sys.path.insert(0, HERE)
import run as cw  # noqa: E402

ok = 0


def check(name, cond):
    global ok
    assert cond, name
    print("  ✓ " + name)
    ok += 1


def snap(price=100.0, rating=4.5, reviews=10, bsr=10000, seller="A", seller_count=None):
    return {"price": price, "rating": rating, "reviews": reviews, "bsr": bsr,
            "seller": seller, "seller_count": seller_count}


# ---------- parse_asins ----------
asins = cw.parse_asins("| B0D62SYW8S | 同行 | 控制臂 |\n| B0GCZBJB9V | 自家 |")
check("从 markdown 表格抽 ASIN（2 个）", len(asins) == 2)
check("去重：同一 ASIN 出现两次只算一个",
      len(cw.parse_asins("B0D62SYW8S B0D62SYW8S")) == 1)
check("非法码不误抓（B0 开头的 10 位才算）",
      cw.parse_asins("B0SHORT B1234567890") == [])

# ---------- 价格：跌/涨走不同阈值 ----------
ch = cw.diff({"X": snap(price=100)}, {"X": snap(price=91)})
check("降价 9% → high（威胁）",
      any(c["kind"] == "降价" and c["level"] == "high" for c in ch))
ch = cw.diff({"X": snap(price=100)}, {"X": snap(price=109)})
check("涨价 9% → medium（机会，不是威胁）",
      any(c["kind"] == "提价" and c["level"] == "medium" for c in ch))
ch = cw.diff({"X": snap(price=100)}, {"X": snap(price=105)})
check("涨 5% 不触发（阈值 8%）", ch == [])

# ---------- 评论 / 评分 ----------
ch = cw.diff({"X": snap(reviews=10)}, {"X": snap(reviews=45)})
check("评论 +35 → 触发评论暴增",
      any(c["kind"] == "评论暴增" for c in ch))
ch = cw.diff({"X": snap(reviews=10)}, {"X": snap(reviews=25)})
check("评论 +15 不触发（阈值 30）", ch == [])
ch = cw.diff({"X": snap(rating=4.6)}, {"X": snap(rating=4.2)})
check("评分掉 0.4 → 触发评分下滑",
      any(c["kind"] == "评分下滑" for c in ch))

# ---------- 跟卖嫌疑（本次新增实现） ----------
ch = cw.diff({"X": snap(seller_count=1)}, {"X": snap(seller_count=3)})
check("卖家数 1→3 → 跟卖嫌疑 high",
      any(c["kind"] == "跟卖嫌疑" and c["level"] == "high" for c in ch))
ch = cw.diff({"X": snap(seller_count=None)}, {"X": snap(seller_count=None)})
check("卖家数字段缺失时跳过（不假装没有跟卖）",
      not any(c["kind"] == "跟卖嫌疑" for c in ch))

# ---------- 对手断货 ----------
ch = cw.diff({"X": snap(seller="A")}, {"X": snap(seller="")})
check("卖家信息消失 → 疑似断货 high",
      any(c["kind"] == "疑似断货" and c["level"] == "high" for c in ch))

# ---------- 置顶排序（SKILL.md 承诺） ----------
many = cw.diff(
    {"A": snap(price=100, reviews=10), "B": snap(seller="S"), "C": snap(seller_count=1)},
    {"A": snap(price=90, reviews=10), "B": snap(seller=""), "C": snap(seller_count=4)})
kinds = [c["kind"] for c in many]
check("变化按影响排序：断货/跟卖排在降价之前",
      kinds.index("疑似断货") < kinds.index("降价") if "降价" in kinds else True)
check("跟卖嫌疑在降价之前",
      kinds.index("跟卖嫌疑") < kinds.index("降价") if "降价" in kinds else True)

# ---------- 首次快照 ----------
check("无上期快照时 diff 返回空（不把首日当变化）", cw.diff(None, {"X": snap()}) == [])

print("\n全部通过：%d 项断言" % ok)
