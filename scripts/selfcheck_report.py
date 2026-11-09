#!/usr/bin/env python3
"""报告交付前自检（每次自动化归档前必跑）。

把用户的验收规范固化成机器检查，不合格就不归档、打告警：
  1. 金额必须 USD，不能有 ¥ / CNY 残留（2026-11-04 口径）
  2. 必须有「计算规则与预警标准」区块（指标怎么算、阈值多少）
  3. 核心报告必须到 SKU 级（SKU 编码列），ASIN 必须可点击跳亚马逊前台
  4. 不能有未替换的模板占位（{title} 之类）
  5. 必须有表格与图文结构（不能退化成纯文本日志）

用法：
  python3 scripts/selfcheck_report.py <报告.html> [报告标题]
  退出码：0=通过；1=有不合格项（详见输出）
"""
import re
import sys
from pathlib import Path

# 必须含 SKU 明细（SKU 编码）的报告标题
SKU_REQUIRED = {"店铺日报", "多店总览", "每日经营简报", "断货预警"}
# 标题允许带店铺后缀：店铺日报-shop_a 等
def _base_title(title):
    return (title or "").split("-")[0].strip()


def check_html(path, title=""):
    p = Path(path)
    errs = []
    if not p.exists():
        return ["文件不存在：%s" % path]
    txt = p.read_text(encoding="utf-8", errors="ignore")
    base = _base_title(title)

    if "¥" in txt or "CNY" in txt:
        errs.append("人民币口径残留（¥/CNY）：金额必须 USD")
    if "计算规则与预警标准" not in txt:
        errs.append("缺「计算规则与预警标准」区块")
    if "<table" not in txt:
        errs.append("没有任何表格（报告不能退化成纯文本日志）")
    if "<svg" not in txt and "<div class=\"kpi" not in txt and "prog-track" not in txt:
        errs.append("缺图文结构（KPI 卡/图表/进度条至少其一）")
    if re.search(r"\{(?:title|subtitle|meta|body|banner|footer|css)\}", txt):
        errs.append("存在未替换的模板占位符")
    if base in SKU_REQUIRED:
        if "SKU 编码" not in txt:
            errs.append("缺 SKU 级明细（SKU 编码列）")
        asins = set(re.findall(r"\bB0[A-Z0-9]{8}\b", txt))
        if asins and "amazon.com/dp/" not in txt:
            errs.append("含 ASIN 但没有可点击的亚马逊前台链接")
    return errs


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    path = sys.argv[1]
    title = sys.argv[2] if len(sys.argv) > 2 else ""
    errs = check_html(path, title)
    if errs:
        print("[selfcheck] FAIL %s（%s）" % (path, title or "未命名"))
        for e in errs:
            print("  ✗ " + e)
        return 1
    print("[selfcheck] PASS %s（%s）" % (path, title or "未命名"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
