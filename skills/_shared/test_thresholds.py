#!/usr/bin/env python3
"""阈值加载回归测试（RED→GREEN 留证用）。

基线 bug：config/thresholds.yaml 里明明有 low_stock_ratio_vs_28d / title_min_chars，
但 load_thresholds 因为环境没装 PyYAML，静默返回残缺内置 defaults，
导致 amz-stockout-alert 与 amz-listing-audit 启动即 KeyError。

铁律：纯标准库（metrics.py 开头写明"无依赖"），所以阈值解析不许 import yaml；
本测试同时保证"文件真被读进来"和"文件读不到时降级表是完整的"。
跑法：python3 skills/_shared/test_thresholds.py
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import metrics as m  # noqa: E402

ok = 0


def check(name, cond):
    global ok
    assert cond, "FAIL: %s" % name
    ok += 1
    print("  ✓ %s" % name)


def main():
    print("真实 config/thresholds.yaml 必须真读出来（基线 KeyError 回归）")
    T = m.load_thresholds()
    check("stockout.low_stock_ratio_vs_28d == 28（stockout 脚本第35行崩的键）",
          T["stockout"]["low_stock_ratio_vs_28d"] == 28)
    check("listing.title_min_chars == 80（listing 脚本第62行崩的键）",
          T["listing"]["title_min_chars"] == 80)
    check("listing.title_max_chars == 200", T["listing"]["title_max_chars"] == 200)
    check("listing.bullet_count_min == 5", T["listing"]["bullet_count_min"] == 5)
    check("listing.description_min_chars == 200", T["listing"]["description_min_chars"] == 200)
    check("fitment.min_oe_ratio == 0.9", T["fitment"]["min_oe_ratio"] == 0.9)
    check("每个分组都带 calibration_status（未校准/不适用），占位值不许伪装成已校准",
          all("calibration_status" in T[g] for g in ("stockout", "ads", "listing", "fitment", "data", "calibration")))

    print("\n标准库解析器：注释、行尾注释、两级缩进、int/float/字符串")
    tmp = tempfile.NamedTemporaryFile("w", suffix=".yaml", delete=False, encoding="utf-8")
    tmp.write("# 头部整行注释\n"
              "stockout:\n"
              "  days_of_supply_alert: 21        # 行尾注释\n"
              "  note: 未校准占位\n"
              "ads:\n"
              "  high_spend_no_order: 15.0\n")
    tmp.close()
    try:
        G = m.load_thresholds(tmp.name)
        check("二级键读到", G["stockout"]["days_of_supply_alert"] == 21)
        check("行尾注释被剥掉", G["stockout"]["note"] == "未校准占位")
        check("float 类型保留", G["ads"]["high_spend_no_order"] == 15.0)
        check("YAML 缺的键由默认值补齐（listing 没在 tmp 里出现）",
              G["listing"]["title_min_chars"] == 80)
    finally:
        os.unlink(tmp.name)

    print("\n文件读不到时：降级表必须完整且带警告，不能缺键让脚本崩")
    D = m.load_thresholds(os.path.join(tempfile.gettempdir(), "amz-no-such-thresholds.yaml"))
    check("降级结果带 _warning 说明未校准", "_warning" in D)
    check("降级 stockout 仍有 low_stock_ratio_vs_28d",
          D["stockout"].get("low_stock_ratio_vs_28d") is not None)
    check("降级 listing 仍有 title_min_chars",
          D["listing"].get("title_min_chars") is not None)

    print("\n全部通过：%d 项断言" % ok)


if __name__ == "__main__":
    main()
