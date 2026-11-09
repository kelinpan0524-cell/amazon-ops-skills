#!/usr/bin/env python3
"""文档链接自检：README/docs/system 里的本地相对链接必须都能打开。

为什么需要：文档一重构（移动/删除文件），旧链接就变死链，读者点进去 404 才发现。
CI/自检里跑一次，比人工点链接靠谱。

用法：
  python3 scripts/check_doc_links.py          # 有问题非零退出
  python3 scripts/check_doc_links.py -v       # 列出每个检查过的链接
"""
import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LINK_RE = re.compile(r"\[([^\]]+)\]\(([^)#]+?)(?:#[^)]*)?\)")
SKIP_PREFIX = ("http://", "https://", "mailto:", "ssh://", "#")


def markdown_files():
    """扫描范围：仓库根、docs/、system/、skills/*/SKILL.md。"""
    files = list(ROOT.glob("*.md"))
    files += list((ROOT / "docs").rglob("*.md"))
    files += list((ROOT / "system").rglob("*.md"))
    files += list((ROOT / "skills").glob("*/SKILL.md"))
    return sorted(set(files))


def check(files):
    bad, checked = [], 0
    for md in files:
        try:
            text = md.read_text(encoding="utf-8")
        except OSError:
            continue
        for m in LINK_RE.finditer(text):
            target = m.group(2).strip()
            if not target or target.startswith(SKIP_PREFIX):
                continue
            checked += 1
            resolved = (md.parent / target).resolve()
            if not resolved.exists():
                bad.append((md.relative_to(ROOT), m.group(1), target))
    return checked, bad


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args()

    files = markdown_files()
    checked, bad = check(files)
    if args.verbose:
        for f in files:
            print("  · %s" % f.relative_to(ROOT))
    print("检查 %d 份文档、%d 个本地链接：%s" % (
        len(files), checked, "全部有效" if not bad else "%d 个失效" % len(bad)))
    for f, label, target in bad:
        print("  ✗ %s → [%s](%s)" % (f, label, target))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
