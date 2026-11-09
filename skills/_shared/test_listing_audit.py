#!/usr/bin/env python3
"""listing-audit 销量 Top5 回归：按 SKU 汇总，重复行折叠、取唯一 Top5。"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "amz-listing-audit", "scripts"))
import run  # noqa: E402

ok = 0


def check(name, cond):
    global ok
    assert cond, name
    print("  ✓ " + name)
    ok += 1


top = run.top_skus_by_sales([
    {"sku": "S1", "units": "10"},
    {"sku": "S1", "units": "5"},   # 重复行：应汇总 15，不是两个 S1
    {"sku": "S2", "units": "3"},
    {"sku": "", "asin": "B0C", "units": "8"},  # 用 asin 兜底
])
check("重复 SKU 汇总后唯一 Top5", top[:3] == ["S1", "B0C", "S2"])
check("只返回唯一 key", len(top) == 3)

print("全部通过：%d 项" % ok)
