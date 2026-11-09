#!/usr/bin/env python3
"""评论监控 diff 逻辑的单测：只报新出现的，差评优先。

为什么值得测：
- 不去重 → 每天报同一批老差评，人直接无视告警（狼来了）；
- 把 4-5 星好评当差评报 → 同样让人失去信任；
- 漏掉 1-2 星 → 产品问题（装不上/尺寸不对）拖半个月才发现，退货率已经上去了。
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "..", "_shared"))
sys.path.insert(0, HERE)
import run as rw  # noqa: E402

ok = 0


def check(name, cond):
    assert cond, name
    print("  ✓ " + name)
    global ok
    ok += 1


def rv(star=5, date="2026-11-01", title="t", content="c"):
    return {"star": star, "date": date, "title": title, "content": content, "sku": ""}


def snap(items):
    return {"date": "2026-11-04", "items": items}


# ---------- 只报新的 ----------
prev = snap({"B0AAAAAAAA": [rv(5, "2026-10-01", "old good")]})
cur = snap({"B0AAAAAAAA": [rv(5, "2026-10-01", "old good"), rv(2, "2026-11-03", "装不上")]})
bad, all_new = rw.diff(prev, cur)
check("老评论不重复报", len(all_new) == 1)
check("新增 2 星进差评列表", len(bad) == 1 and bad[0]["star"] == 2)

# ---------- 好评不算差评 ----------
prev = snap({"B0AAAAAAAA": [rv(5, "2026-10-01", "a")]})
cur = snap({"B0AAAAAAAA": [rv(5, "2026-10-01", "a"), rv(5, "2026-11-03", "很好")]})
bad, all_new = rw.diff(prev, cur)
check("新 5 星算新评论但不算差评", len(all_new) == 1 and bad == [])

# ---------- 边界星级 ----------
prev = snap({})
for star, expect in ((1, True), (3, True), (4, False), (5, False)):
    cur = snap({"B0AAAAAAAA": [rv(star, "2026-11-03", "x")]})
    bad, _ = rw.diff(prev, cur)
    check("★%d %s差评" % (star, "算" if expect else "不算"), bool(bad) == expect)

# ---------- 首次运行 ----------
bad, all_new = rw.diff(None, snap({"B0AAAAAAAA": [rv(1, "2026-11-03", "x")]}))
check("首次运行（无基准）所有评论都算新", len(all_new) == 1)

# ---------- 多 ASIN ----------
prev = snap({"B0AAAAAAAA": [], "B0BBBBBBBB": []})
cur = snap({"B0AAAAAAAA": [rv(2, "2026-11-03", "bad A")],
            "B0BBBBBBBB": [rv(5, "2026-11-03", "good B")]})
bad, all_new = rw.diff(prev, cur)
check("多 ASIN 分别统计", len(all_new) == 2 and len(bad) == 1 and bad[0]["asin"] == "B0AAAAAAAA")

# ---------- 排序 ----------
prev = snap({})
cur = snap({"B0AAAAAAAA": [rv(5, "2026-11-03", "good"), rv(1, "2026-11-02", "bad"),
                          rv(3, "2026-11-01", "meh")]})
bad, _ = rw.diff(prev, cur)
check("差评按星级升序（1 星在最前）", [b["star"] for b in bad] == [1, 3])

# ---------- 去重键 ----------
check("同日期同标题视为同一条",
      rw._review_key(rv(5, "2026-11-01", "same title")) ==
      rw._review_key(rv(1, "2026-11-01", "same title")))
check("同日期不同标题算两条",
      rw._review_key(rv(5, "2026-11-01", "a")) != rw._review_key(rv(5, "2026-11-01", "b")))

# ---------- 字段解析 ----------
n = rw.normalize({"rating": "2", "date": "2026-11-03T10:00:00Z", "title": "t", "review": "c"})
check("rating/date/review 别名都能认", n["star"] == 2 and n["date"] == "2026-11-03")
n = rw.normalize({"star": "abc"})
check("星级解析失败给 None 而不是 0（0 会被误判成差评）", n["star"] is None)

print("\n全部通过：%d 项断言" % ok)
