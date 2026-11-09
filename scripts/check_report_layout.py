#!/usr/bin/env python3
"""HTML 报告排版自检：SVG 文字溢出 / 重叠 / 容器横向溢出。

为什么需要：图表是脚本拼字符串画的，长数字（如 "297,867.5"）很容易冲出 viewBox；
中文标签估算宽度更难。这类问题肉眼扫一遍容易漏，用静态分析兜底。

用法：
  python3 scripts/check_report_layout.py                    # 检查 data/reports 下全部 html
  python3 scripts/check_report_layout.py --file a.html      # 检查单个
  python3 scripts/check_report_layout.py --strict           # 有告警即非零退出（CI 用）

判定口径（估算，非像素级）：
  - 英文/数字 0.55em/字符、中文 1.0em/字符；
  - font-size 从 class 推断（.pt 10px / .tick 10px / .legend 11px / .chart-title 12px）；
  - 右边界容差 2px、重叠容差 3px。
"""
import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REPORTS = ROOT / "data" / "reports"

SVG_RE = re.compile(r"<svg[^>]*viewBox=\"0 0 (\d+(?:\.\d+)?) (\d+(?:\.\d+)?)\"[^>]*>(.*?)</svg>", re.S)
TEXT_RE = re.compile(r"<text([^>]*)>(.*?)</text>", re.S)
ATTR_RE = re.compile(r'(\w[\w-]*)="([^"]*)"')

FONT_BY_CLASS = {"pt": 10.0, "tick": 10.0, "legend": 11.0, "chart-title": 12.0,
                 "hlabel": 11.0, "hval": 11.0, "donut-center": 13.0}
DEFAULT_FONT = 11.0


def char_width(ch: str, size: float) -> float:
    """单个字符的估算宽度：CJK 全宽，ASCII 0.55 宽。"""
    return size * (1.0 if ord(ch) > 0x2E80 else 0.55)


def est_width(s: str, size: float) -> float:
    return sum(char_width(ch, size) for ch in s)


def font_size(cls: str) -> float:
    for k, v in FONT_BY_CLASS.items():
        if k in cls.split():
            return v
    return DEFAULT_FONT


def check_file(path):
    """返回 [(问题类型, 详情)]。"""
    html = path.read_text(encoding="utf-8")
    issues = []
    for si, m in enumerate(SVG_RE.finditer(html)):
        vw, vh, body = float(m.group(1)), float(m.group(2)), m.group(3)
        boxes = []
        for tm in TEXT_RE.finditer(body):
            attrs = dict(ATTR_RE.findall(tm.group(1)))
            content = re.sub(r"<[^>]+>", "", tm.group(2)).strip()
            if not content:
                continue
            try:
                x, y = float(attrs.get("x", 0)), float(attrs.get("y", 0))
            except ValueError:
                continue
            cls = attrs.get("class", "")
            size = font_size(cls)
            w = est_width(content, size)
            anchor = attrs.get("text-anchor", "start")
            if anchor == "middle":
                x0 = x - w / 2
            elif anchor == "end":
                x0 = x - w
            else:
                x0 = x
            x1 = x0 + w
            if x1 > vw + 2:
                issues.append(("svg-text-out-right",
                               "svg#%d 「%s」右边缘 %.0f > 画布 %.0f（超出 %.0fpx）"
                               % (si, content[:24], x1, vw, x1 - vw)))
            if x0 < -2:
                issues.append(("svg-text-out-left",
                               "svg#%d 「%s」左边缘 %.0f < 0" % (si, content[:24], x0)))
            # 纵向也要判（此前只判了横向，底部标签溢出检测不到）
            if y + size * 0.3 > vh + 2:
                issues.append(("svg-text-out-bottom",
                               "svg#%d 「%s」底部 %.0f > 画布高 %.0f（超出 %.0fpx）"
                               % (si, content[:24], y + size * 0.3, vh, y + size * 0.3 - vh)))
            if y - size > vh:
                issues.append(("svg-text-out-top",
                               "svg#%d 「%s」顶部 %.0f 超出画布" % (si, content[:24], y - size)))
            boxes.append((content, x0, x1, y - size, y + size * 0.25))
        # 重叠检测（同一 SVG 内两两比较，容差 3px）
        for a in range(len(boxes)):
            for b in range(a + 1, len(boxes)):
                ca, a0, a1, at, ab = boxes[a]
                cb, b0, b1, bt, bb = boxes[b]
                ox = min(a1, b1) - max(a0, b0)
                oy = min(ab, bb) - max(at, bt)
                if ox > 3 and oy > 3:
                    issues.append(("svg-text-overlap",
                                   "svg#%d 「%s」与「%s」重叠 %dx%d"
                                   % (si, ca[:14], cb[:14], ox, oy)))
    return issues


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--file", default="")
    ap.add_argument("--strict", action="store_true")
    args = ap.parse_args()

    if args.file:
        targets = [Path(args.file)]
    else:
        targets = sorted(REPORTS.rglob("*.html")) if REPORTS.exists() else []
    if not targets:
        print("没有可检查的 HTML 报告（先跑一遍技能生成报告）")
        return 0

    total = 0
    for p in targets:
        issues = check_file(p)
        rel = p.relative_to(ROOT) if str(p).startswith(str(ROOT)) else p
        if issues:
            total += len(issues)
            print("✗ %s：%d 个问题" % (rel, len(issues)))
            for kind, detail in issues[:8]:
                print("    [%s] %s" % (kind, detail))
        else:
            print("✓ %s" % rel)
    print("\n合计 %d 个问题（检查 %d 份报告）" % (total, len(targets)))
    return 1 if (args.strict and total) else 0


if __name__ == "__main__":
    sys.exit(main())
