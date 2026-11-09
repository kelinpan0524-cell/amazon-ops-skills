#!/usr/bin/env python3
"""竞品差评归类的单测。

为什么值得测：归类错了会给出错误的选品建议。
比如把「装不上」误判成「质量问题」，结论就从"它 fitment 烂、你快上"变成
"它质量差、有门槛"——方向完全反了。
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "..", "_shared"))
sys.path.insert(0, HERE)
import run as ri  # noqa: E402

ok = 0


def check(name, cond):
    assert cond, name
    print("  ✓ " + name)
    global ok
    ok += 1


def cat(text):
    return ri.classify(text)


# 装不上（最高优先级：这是选品机会的核心信号）
for t in ("Does not fit my 2015 Camry",
          "didn't fit at all",
          "Wrong part for my vehicle",
          "not compatible with my model",
          "won't fit"):
    check("装不上：%s" % t[:28], cat(t) == "装不上/适配错")

# 尺寸
check("尺寸：too small", cat("The bolts were too short for the bracket") == "尺寸/规格不对")
check("尺寸：mm", cat("Listed as 12mm but measured 10mm") == "尺寸/规格不对")

# 质量
check("质量：broke", cat("Broke after two months") == "质量问题")
check("质量：cheap", cat("Feels cheap and flimsy") == "质量问题")

# 物流
check("物流：arrived damaged", cat("Arrived damaged, box was crushed") == "物流/包装")
check("物流：missing", cat("Missing bolts in the package") == "物流/包装")

# 描述不符
check("描述不符：not as described", cat("Not as described, picture shows two pieces") == "描述不符")

# 价格
check("价格：overpriced", cat("Way overpriced for what you get") == "价格/性价比")

# 安装困难
check("安装难：no instructions", cat("Hard to install, no instructions included") == "安装困难")

# 优先顺序：同时命中「装不上」和「尺寸」时，装不上优先（更具体的信号）
check("同时命中时装不上优先", cat("Wrong size, does not fit") == "装不上/适配错")

# 中文评论归不了（诚实：不硬猜）
check("中文评论归不出类（不硬猜）", cat("装不上，尺寸不对") is None)

# 好评不该被归类（调用方只传差评，但防御一下）
check("空文本返回 None", cat("") is None)

# 分析函数：只统计 1-3 星
snap = {"date": "2026-11-04", "items": {"B0AAAAAAAA": [
    {"star": 5, "title": "great", "content": "works perfectly", "date": "2026-11-01"},
    {"star": 1, "title": "doesn't fit", "content": "wrong part for my car", "date": "2026-11-02"},
    {"star": 2, "title": "broke", "content": "broke after a week", "date": "2026-11-03"},
]}}
res = ri.analyze(snap)
check("只统计 1-3 星（5 星不算）", res[0]["bad"] == 2)
check("差评率按总评论算", abs(res[0]["rate"] - 2 / 3) < 1e-9)
check("分成两个问题类型", len(res[0]["buckets"]) == 2)

# 没差评的 ASIN 不出现在结果里
res2 = ri.analyze({"date": "2026-11-04", "items": {"B0BBBBBBBB": [
    {"star": 5, "title": "ok", "content": "fine", "date": "2026-11-01"}]}})
check("没差评的 ASIN 不出现", res2 == [])

print("\n全部通过：%d 项断言" % ok)
