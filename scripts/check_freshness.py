#!/usr/bin/env python3
"""保鲜期检查：哪些技能/知识条目该复核了。

只读不写。扫描 skills/*/SKILL.md 与 knowledge/**/*.md 头部的 last_verified /
review_by / as_of，列出超期的，并给出该去哪核实。

用法：
  python3 scripts/check_freshness.py            # 只列超期的
  python3 scripts/check_freshness.py --all      # 连没过期的也列出来
  python3 scripts/check_freshness.py --warn-days 14   # 提前 14 天预警
"""
import argparse
import datetime as dt
import glob
import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# 去哪核实：按文件路径关键字匹配
SOURCES = [
    (r"listing|image", "Seller Central 图片/Listing 规范"),
    (r"ads|advertising", "Seller Central 广告费率与政策 + 自有手册第八章"),
    (r"tariff|hs_?code|duty", "海关税则与官方公告"),
    (r"stockout|inventory", "亚马逊低库存限流政策 + 领星库存口径"),
    (r"knowledge/", "原始出处（飞书知识库）复核"),
]


def front_matter(path):
    try:
        with open(path) as f:
            text = f.read(4000)
    except OSError:
        return {}
    if not text.startswith("---"):
        return {}
    try:
        body = text.split("---", 2)[1]
    except IndexError:
        return {}
    data = {}
    for line in body.splitlines():
        if ":" in line and not line.strip().startswith("#"):
            k, v = line.split(":", 1)
            data[k.strip()] = v.strip().strip('"')
    return data


def parse_date(s):
    try:
        return dt.date.fromisoformat(s)
    except (TypeError, ValueError):
        return None


def suggest_source(path):
    p = path.lower()
    for pat, src in SOURCES:
        if re.search(pat, p):
            return src
    return "官方文档或原始出处"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--warn-days", type=int, default=0)
    args = ap.parse_args()

    today = dt.date.today()
    targets = sorted(glob.glob(os.path.join(ROOT, "skills/*/SKILL.md")))
    targets += sorted(glob.glob(os.path.join(ROOT, "knowledge/**/*.md"), recursive=True))

    overdue, soon, ok, unknown = [], [], 0, []
    for path in targets:
        fm = front_matter(path)
        rel = os.path.relpath(path, ROOT)
        due = parse_date(fm.get("review_by"))
        verified = parse_date(fm.get("last_verified")) or parse_date(fm.get("as_of"))
        if due is None and verified is None:
            unknown.append(rel)
            continue
        if due is None:
            ok += 1
            continue
        days = (due - today).days
        if days < 0:
            overdue.append((days, rel, verified.isoformat() if verified else "未标"))
        elif days <= args.warn_days:
            soon.append((days, rel, due.isoformat()))
        else:
            ok += 1

    print("【该复核了】%d 个" % len(overdue))
    for days, rel, verified in sorted(overdue)[:30]:
        print("  - %s（过期 %d 天，上次核实 %s）→ 去哪查：%s" % (rel, -days, verified, suggest_source(rel)))
    if len(overdue) > 30:
        print("  … 还有 %d 个" % (len(overdue) - 30))

    if soon:
        print("\n【快到期】%d 个（%d 天内）" % (len(soon), args.warn_days or 0))
        for days, rel, due in sorted(soon)[:10]:
            print("  - %s（%s 到期）" % (rel, due))

    print("\n【其余】%d 个在保鲜期内；%d 个没标日期" % (ok, len(unknown)))
    if unknown and args.all:
        for rel in unknown[:20]:
            print("  - 未标 last_verified / review_by：%s" % rel)

    if overdue and not unknown:
        print("\n做法：逐条核实 → 更新头部 last_verified 与 review_by → 规则真变了才改正文。")
    print("\n保鲜期标准见 system/FRESHNESS.md；改完记一行到 config/CHANGELOG.md。")


if __name__ == "__main__":
    main()
