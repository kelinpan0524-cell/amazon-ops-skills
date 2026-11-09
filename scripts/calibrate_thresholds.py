#!/usr/bin/env python3
"""阈值校准：用我们自己的历史分布 + 行业基准，给出有依据的阈值建议。

为什么要有这一步：`config/thresholds.yaml` 里多数阈值原本是"占位值"，
改不改、改成多少全靠感觉。这个脚本把「拍脑袋」换成「看分布」：

  1. 读 data/normalized/shop_monthly.csv（逐月历史，`fetch_lingxing.py --mode monthly` 产出）
  2. 算 ACOS / 退货率的分位数（P50 / P75 / P90 / P95）与均值
  3. 叠加外部硬基准（如亚马逊汽配退货率收费线 9.1%）
  4. 输出建议阈值，并标注每条的依据

用法：
  python3 scripts/calibrate_thresholds.py            # 只看建议（不动配置）
  python3 scripts/calibrate_thresholds.py --strict   # 数据不足时非零退出

注意：本脚本**只给建议，不改 thresholds.yaml**——改阈值要人确认后手改，
并写 config/CHANGELOG.md（仓库规矩）。
"""
import argparse
import json
import statistics
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "skills" / "_shared"))
import metrics as m  # noqa: E402

# 外部硬基准（查证于 2026-11-04；来源见 docs/THRESHOLD-CALIBRATION.md）
EXTERNAL = {
    "amazon_auto_return_threshold": 0.091,
    # 亚马逊 Automotive & Powersports 类目退货率阈值（2024-06-01 起生效）：
    # 超过它才收退货处理费；月发货 <25 件豁免。这是**官方收费线**，比行业均值更有约束力。
    "auto_fitment_parts_return_range": (0.12, 0.18),
    # 车型专用件的行业平均退货率（第三方分析口径，方向性参考）
    "fitment_error_share_of_returns": 0.187,
    # 汽配退货里约 18.7% 归因于适配数据不完整/错误（Marketplace Pulse 2025 口径）
}


def pct(vals, q):
    """分位数（线性插值）；空列表返回 None。"""
    if not vals:
        return None
    s = sorted(vals)
    if len(s) == 1:
        return s[0]
    pos = (len(s) - 1) * q
    lo, hi = int(pos), min(int(pos) + 1, len(s) - 1)
    return s[lo] + (s[hi] - s[lo]) * (pos - lo)


def load_months():
    """读月度表，只保留有 month 字段的行（YYYY-MM）。"""
    return [r for r in m.load("shop_monthly") if str(r.get("month", "")).strip()]


def stats(vals, label):
    vals = [v for v in vals if v is not None]
    if not vals:
        return None
    return {
        "label": label, "n": len(vals),
        "p50": pct(vals, 0.50), "p75": pct(vals, 0.75),
        "p90": pct(vals, 0.90), "p95": pct(vals, 0.95),
        "mean": statistics.fmean(vals),
        "min": min(vals), "max": max(vals),
    }


def fmt(v, nd=1):
    return "-" if v is None else ("%.*f%%" % (nd, v * 100))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--strict", action="store_true", help="历史不足 6 个月时非零退出")
    args = ap.parse_args()

    rows = load_months()
    if not rows:
        print("没有 shop_monthly 数据。先跑：python3 scripts/fetch_lingxing.py --mode monthly --months 24")
        return 2 if args.strict else 0

    months = sorted({str(r.get("month", "")).strip() for r in rows if r.get("month")})
    print("历史覆盖：%d 个店铺月（%s ~ %s）\n" % (
        len(rows), months[0] if months else "?", months[-1] if months else "?"))

    acos_vals = [m.num(r.get("acos")) for r in rows]
    ret_vals = [m.num(r.get("return_rate")) for r in rows]
    tacos_vals = []
    for r in rows:
        rev, spend = m.num(r.get("revenue")), m.num(r.get("spend"))
        tacos_vals.append(spend / rev if rev else None)

    acos_s = stats(acos_vals, "ACOS")
    ret_s = stats(ret_vals, "退货率")
    tacos_s = stats(tacos_vals, "TACOS")

    print("=== 我们自己的分布（按店铺月，n=%d）===" % len(rows))
    for s in (acos_s, ret_s, tacos_s):
        if s:
            print("  %-6s P50 %s | P75 %s | P90 %s | P95 %s | 均值 %s | 区间 %s~%s（n=%d）"
                  % (s["label"], fmt(s["p50"]), fmt(s["p75"]), fmt(s["p90"]), fmt(s["p95"]),
                     fmt(s["mean"]), fmt(s["min"]), fmt(s["max"]), s["n"]))

    print("\n=== 建议阈值（依据写在括号里）===")
    suggestions = []

    # ACOS：业务方定调 >18% 算高；用 P90 交叉验证
    acos_hi = 0.18
    if acos_s and acos_s["p90"]:
        note = ("业务定调 18%%；历史 P90=%s、均值=%s" % (fmt(acos_s["p90"]), fmt(acos_s["mean"])))
    else:
        note = "业务定调 18%（历史不足，未做交叉验证）"
    suggestions.append(("ads.acos_high_watch", acos_hi, "medium", note))
    suggestions.append(("ads.acos_high_critical", round(max(0.25, (acos_s or {}).get("p95") or 0), 4),
                        "critical",
                        "P95 与 25% 取高者（再高就不是波动，是投放跑偏）"))

    # 退货率：亚马逊汽配官方收费线 9.1% 是硬指标；watch 线设在接近它
    amz = EXTERNAL["amazon_auto_return_threshold"]
    suggestions.append(("alert_rules.return_rate_watch", 0.08, "medium",
                        "接近亚马逊汽配收费线 9.1%% 前先预警（历史均值 %s）"
                        % (fmt(ret_s["mean"]) if ret_s else "-")))
    suggestions.append(("alert_rules.return_rate_critical", amz, "critical",
                        "亚马逊 Automotive & Powersports 类目退货率阈值 9.1%——超过即收退货处理费（官方口径）"))

    # TACOS：看我们自己的分布，取 P90
    if tacos_s and tacos_s["p90"]:
        suggestions.append(("ads.tacos_high", round(tacos_s["p90"], 4), "medium",
                            "历史 P90（TACOS 没有外部基准，只看自己是否异常）"))

    for key, val, level, note in suggestions:
        shown = ("%.0f%%" % (val * 100)) if isinstance(val, float) else str(val)
        print("  %-38s %-8s %-9s %s" % (key, shown, level, note))

    print("\n=== 与当前配置对比 ===")
    cur = m.load_thresholds()
    checks = [
        ("ads.acos_tolerance_over_breakeven", cur.get("ads", {}).get("acos_tolerance_over_breakeven")),
        ("alert_rules.acos-high（预警用）", _alert_threshold("acos-high")),
        ("alert_rules.acos-critical", _alert_threshold("acos-critical")),
        ("alert_rules.return-rate-watch", _alert_threshold("return-rate-watch")),
        ("alert_rules.return-rate-critical", _alert_threshold("return-rate-critical")),
    ]
    for name, v in checks:
        print("  %-52s %s" % (name, ("%.0f%%" % (v * 100)) if isinstance(v, (int, float)) else v))

    print("\n下一步：确认后手改 config/alert_rules.json 与 config/thresholds.yaml，"
          "\n        并写一行 config/CHANGELOG.md（改什么、为什么、依据哪条判断）。")

    if args.strict and len(months) < 6:
        print("\n✗ 历史不足 6 个月，分布不可信（--strict）")
        return 1
    return 0


def _alert_threshold(rule_id):
    """读 alert_rules.json 里某条规则的 threshold。"""
    p = ROOT / "config" / "alert_rules.json"
    try:
        rules = json.loads(p.read_text(encoding="utf-8")).get("rules", [])
    except (OSError, json.JSONDecodeError):
        return None
    for r in rules:
        if r.get("id") == rule_id:
            return r.get("threshold")
    return None


if __name__ == "__main__":
    sys.exit(main())
