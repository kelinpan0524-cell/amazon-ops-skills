#!/usr/bin/env python3
"""shopdata 的单测：口径细节最容易走偏，每条断言写明"为什么"。"""
import datetime as dt
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import shopdata as sd  # noqa: E402

ok = 0


def check(name, cond):
    global ok
    assert cond, name
    print("  ✓ " + name)
    ok += 1


def near(a, b, tol=1e-9):
    return a is not None and b is not None and abs(a - b) <= tol


# ---------- val / ratio ----------
check("val 缺数返回 None（不冒充 0）", sd.val({}, "units") is None)
check("val 空串返回 None", sd.val({"units": ""}, "units") is None)
check("val 脏格式能清洗（$1,234.5）", near(sd.val({"revenue": "$1,234.5"}, "revenue"), 1234.5))
check("ratio 正常", near(sd.ratio(120, 100), 0.2))
check("ratio 上期为 0 返回 None（不编 0%）", sd.ratio(100, 0) is None)
check("ratio 上期缺失返回 None", sd.ratio(100, None) is None)
check("fmt_delta 格式化", sd.fmt_delta(0.123) == "+12%" and sd.fmt_delta(None) == "无基线")

# ---------- 分组与最新完整日 ----------
by_shop = {
    "shop_a": {"2026-11-01": {"units": 10}, "2026-11-02": {"units": 20},
              "2026-11-03": {"units": 30}},
    "shop_b": {"2026-11-02": {"units": 5}, "2026-11-03": {"units": 7}},
}
picked = sd.latest_by_shop(by_shop, today="2026-11-04")
check("各店各取最新完整日（shop_a=11-03）", picked["shop_a"][0] == "2026-11-03")
check("各店允许不同步（shop_b 也只有 11-03）", picked["shop_b"][0] == "2026-11-03")

# 今天的数据要跳过（领星当天未产齐）
by_shop2 = {"shop_a": {"2026-11-02": {"units": 5}, "2026-11-04": {"units": 0}}}
p2 = sd.latest_by_shop(by_shop2, today="2026-11-04")
check("今天的数据被跳过（取 11-02 而不是 11-04）", p2["shop_a"][0] == "2026-11-02")
p3 = sd.latest_by_shop({"shop_a": {"2026-11-04": {"units": 1}}}, today="2026-11-04")
check("只有今天数据时仍返回它（不返回空）", p3["shop_a"][0] == "2026-11-04")

prev = sd.previous_by_shop(by_shop, picked)
check("上一期取该店前一个日期", near(sd.val(prev["shop_a"], "units"), 20.0))

# ---------- 区间汇总 ----------
per_shop, total, covered = sd.aggregate(by_shop, "2026-11-01", "2026-11-02")
check("区间汇总按店计算", near(per_shop["shop_a"]["units"], 30.0))
check("区间汇总跨店合计", near(total["units"], 35.0))
check("covered_days 是表内真实天数（2 天）", covered == 2)

_, _, covered_empty = sd.aggregate(by_shop, "2026-10-01", "2026-10-31")
check("无数据区间 covered=0", covered_empty == 0)

# ---------- 可比性 ----------
check("覆盖 7/7 天可比", sd.is_comparable(7, 7))
check("覆盖 4/7 天不可比（不足 70%）", not sd.is_comparable(4, 7))
check("覆盖 5/7 天可比（恰好 71%）", sd.is_comparable(5, 7))
check("期望 0 天时不可比", not sd.is_comparable(0, 0))

# ---------- 周/月边界 ----------
s, e, ps, pe, ys, ye = sd.week_bounds("2026-W45")
check("周锚点：2026-W45 起于周一 11-02", s == dt.date(2026, 11, 2))
check("周锚点：止于周日 11-08", e == dt.date(2026, 11, 8))
check("上期是紧邻上一周", ps == dt.date(2026, 10, 26) and pe == dt.date(2026, 11, 1))
check("去年同期=去年同 ISO 周的周一", ys.isocalendar()[1] == s.isocalendar()[1] and ys.weekday() == 0)

ms, me, mps, mpe, mys, mye = sd.month_bounds("2026-10")
check("月锚点：2026-10 起止正确", ms == dt.date(2026, 10, 1) and me == dt.date(2026, 10, 31))
check("上月是 2026-09", mps == dt.date(2026, 9, 1) and mpe == dt.date(2026, 9, 30))
check("去年同月是 2025-10", mys == dt.date(2025, 10, 1) and mye == dt.date(2025, 10, 31))

# 跨年边界
s2, e2, ps2, _, ys2, _ = sd.week_bounds("2026-W01")
check("跨年周：2026-W01 上期落在 2025 年", ps2.year == 2025)
m3s, _, m3ps, _, m3ys, _ = sd.month_bounds("2026-01")
check("跨年月：2026-01 上月是 2025-12", m3ps == dt.date(2025, 12, 1))
check("跨年月：去年同期是 2025-01", m3ys == dt.date(2025, 1, 1))

print("\n全部通过：%d 项断言" % ok)
