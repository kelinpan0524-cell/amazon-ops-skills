#!/usr/bin/env python3
"""import_lingxing.py 回归：裸表头映射、可选列不降级、raw 同名移入 superseded。"""
import os
import shutil
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import import_lingxing as imp  # noqa: E402

ok = 0


def check(name, cond):
    global ok
    assert cond, name
    print("  ✓ " + name)
    ok += 1


# 1) 裸表头「可售」被 sniff 识别但之前不映射 → 必须映射到 fba_available
recs, _ = imp.normalize([{"日期": "2026/11/1", "可售": "15", "sku": "S1"}], "inventory_daily")
check("裸表头『可售』映射 fba_available", recs[0].get("fba_available") == "15")
check("日期归一成 ISO（2026/11/1 → 2026-11-01）", recs[0]["date"] == "2026-11-01")

# 1b) 多行表头（领星真实形态：换行 + 括号说明 + 英文副标）也能映射
recs_m, _ = imp.normalize([{"日期\n(美西时间)": "2026-11-03 00:00:00", "产品\nASIN": "B0A",
                            "会话数\nSessions": "120", "销量\n(订购数量)": "8",
                            "销售额\n($)": "$1,234.50"}], "sales_daily")
check("多行表头『会话数\\nSessions』映射 sessions", recs_m[0].get("sessions") == "120")
check("多行表头『产品\\nASIN』映射 asin", recs_m[0].get("asin") == "B0A")
check("『销售额\\n($)』映射 revenue（透传，读取侧清洗）", recs_m[0].get("revenue") == "$1,234.50")
check("xlsx 时间戳归一（2026-11-03 00:00:00 → 2026-11-03）", recs_m[0]["date"] == "2026-11-03")

# 1c) 日期列缺失 → normalize 拒绝整表（SystemExit，不许静默填今天）
try:
    imp.normalize([{"sku": "S1", "可售": "15"}], "inventory_daily")
    refused = False
except SystemExit:
    refused = True
check("无日期列 → normalize 报 SystemExit 拒绝整表", refused)

# 1d) 表头映射防误伤：'oe' 不命中 'goes'（词边界）
check("短英文别名要求词边界（oe 不命中 goes）", imp.map_header("goes to school") is None)
check("精确别名仍生效", imp.map_header("OE") == "oe_number")

# 2) 可选观察列缺失不降级；关键字段缺失才 degraded
rows = [{"date": "2026-11-01", "sku": "S1", "asin": "B0A", "fba_available": "5", "fba_inbound": "0"}] * 3
q = imp.quality_of(rows, "inventory_daily")
check("可选列（days_of_supply 等）缺失不降级",
      q["quality"] == "ok" and "days_of_supply" in q["missing"])
rows2 = [{"date": "2026-11-01", "days_of_supply": "7"}] * 3
q2 = imp.quality_of(rows2, "inventory_daily")
check("关键字段（sku/asin/fba_available）缺失 → degraded", q2["quality"] == "degraded")

# 边界：inventory 5 个关键列，fba_available 整列 100% 空 = 恰好 20%，必须 degraded
rows3 = [{"date": "2026-11-01", "sku": "S%d" % i, "asin": "B0%d" % i, "fba_inbound": "0"}
         for i in range(3)]
q3 = imp.quality_of(rows3, "inventory_daily")
check("恰好 20%（关键列整列空 fba_available）必须 degraded", q3["quality"] == "degraded")

# 边界：10 个关键列里恰好 2 列整空 = 20%，同样必须 degraded（避免列变多后漏判）
imp.SCHEMA["__test10__"] = {"need_any": [["k1"]],
                            "cols": ["k1", "k2", "k3", "k4", "k5", "k6", "k7", "k8", "k9", "k10"]}
imp.OPTIONAL_COLS["__test10__"] = []
rows4 = [{"k1": "a", "k2": "b"}, {"k1": "c", "k2": "d"}]
q4 = imp.quality_of(rows4, "__test10__")
check("10 关键列恰好 20% 整空（k3..k10）必须 degraded", q4["quality"] == "degraded")
del imp.SCHEMA["__test10__"]
del imp.OPTIONAL_COLS["__test10__"]

# 3) raw 同日同名：旧文件移入 superseded，新文件就位，只增不删
tmp = tempfile.mkdtemp()
raw_dir = os.path.join(tmp, "raw", "2026-11-04")
os.makedirs(raw_dir)
open(os.path.join(raw_dir, "产品表现.csv"), "w").write("OLD")
src = os.path.join(tmp, "产品表现.csv")
open(src, "w").write("NEW")
imp.stage_raw(src, raw_dir)
check("新 raw 就位", open(os.path.join(raw_dir, "产品表现.csv")).read() == "NEW")
check("旧 raw 移入 superseded（只增不删）",
      "superseded" in os.listdir(raw_dir)
      and any("OLD" in open(os.path.join(raw_dir, "superseded", f)).read()
              for f in os.listdir(os.path.join(raw_dir, "superseded"))))
shutil.rmtree(tmp)

print("全部通过：%d 项" % ok)
