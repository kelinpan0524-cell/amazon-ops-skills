#!/usr/bin/env python3
"""同事解压后跑这一个：从模板生成自己的配置，并检查环境。

用法：
  python3 scripts/setup_local.py

做的事：
  1. config/*.json 不存在就从 *.example.json 复制一份
  2. 检查 python 版本、必需文件、可选的 MCP 环境变量
  3. 把"接下来要做什么"一条条打出来

它**不联网、不改外部系统**，只在本机生成配置文件。
"""
import argparse
import json
import os
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CONFIG = ROOT / "config"
sys.path.insert(0, str(ROOT / "skills" / "_shared"))
import mcp_client as mc  # noqa: E402  （凭证：环境变量优先，config/mcp.local.json 兜底）
PAIRS = [
    ("shops.example.json", "shops.json", "店铺组 + 领星店铺 ID"),
    ("targets.example.json", "targets.json", "年度/店铺销售目标"),
    ("competitors.example.json", "competitors.json", "竞对与同款我方 ASIN 映射"),
    ("watchlist.example.json", "watchlist.json", "要盯的自有 ASIN（跟卖/评论监控）"),
    ("mcp.local.example.json", "mcp.local.json", "MCP 凭证（GUI 客户端兜底，环境变量优先）"),
]

TODO = []


def ensure_config():
    print("=" * 62)
    print("1. 配置文件")
    print("=" * 62)
    for example, real, what in PAIRS:
        src, dst = CONFIG / example, CONFIG / real
        if dst.exists():
            print("  ✓ %-22s 已存在（%s）" % (real, what))
            continue
        if not src.exists():
            print("  ! %-22s 模板缺失，跳过" % real)
            continue
        shutil.copyfile(src, dst)
        print("  + %-22s 从模板生成，**需要你填**（%s）" % (real, what))
        TODO.append("编辑 config/%s（%s）" % (real, what))
    # alert_rules / thresholds 是通用规则，没有 example 也能跑
    for name in ("alert_rules.json", "thresholds.yaml", "automations.yaml"):
        p = CONFIG / name
        print("  %s %-22s %s" % ("✓" if p.exists() else "!", name,
                                 "在" if p.exists() else "缺失（从仓库补一份）"))


def check_env():
    print()
    print("=" * 62)
    print("2. 运行环境")
    print("=" * 62)
    major, minor = sys.version_info[:2]
    ok = (major, minor) >= (3, 9)
    print("  %s Python %d.%d（需要 ≥3.9）" % ("✓" if ok else "✗", major, minor))
    if not ok:
        TODO.append("升级 Python 到 3.9+")

    for name, why, need in (
            ("lark-cli", "发飞书报告/写多维表格", False),
            ("git", "更新代码", False)):
        found = shutil.which(name)
        print("  %s %-10s %s%s" % ("✓" if found else "-", name, why,
                                   "" if found else "（可选，装了才能用）"))

    lx_url, lx_key = mc.credential("lingxing", "LINGXING_MCP_URL", "LINGXING_MCP_KEY")
    _, ss_key = mc.credential("sellersprite", "SELLERSPRITE_MCP_KEY", "SELLERSPRITE_MCP_KEY")
    for label, has, need, hint in (
            ("领星 MCP（url+key）", bool(lx_url and lx_key), True,
             "export LINGXING_MCP_URL/LINGXING_MCP_KEY，或填 config/mcp.local.json"),
            ("卖家精灵密钥（选品/竞品/跟卖要用）", bool(ss_key), False,
             "export SELLERSPRITE_MCP_KEY，或填 config/mcp.local.json")):
        mark = "✓" if has else ("!" if need else "-")
        print("  %s %-34s %s" % (mark, label, "" if has else hint))
        if not has and need:
            TODO.append("%s（见 docs/CLIENTS.md）" % hint)
    print("  → 凭证来源：%s" % mc.where_credentials_come_from())


def check_files():
    print()
    print("=" * 62)
    print("3. 关键文件")
    print("=" * 62)
    need = ["README.md", "skills", "scripts", "docs", "config"]
    for n in need:
        p = ROOT / n
        print("  %s %s" % ("✓" if p.exists() else "✗", n))
        if not p.exists():
            TODO.append("文件缺失：%s（包不完整，重新解压）" % n)
    n_skills = len([p for p in (ROOT / "skills").iterdir()
                    if p.is_dir() and (p / "SKILL.md").exists()]) \
        if (ROOT / "skills").exists() else 0
    print("  → 技能 %d 个" % n_skills)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--allow-incomplete", action="store_true",
        help="生成占位配置并检查环境后返回 0；供克隆验收/CI 使用，不代表密钥已配置")
    args = parser.parse_args(argv)
    print()
    print("示例公司 · 亚马逊运营技能包 —— 本机初始化")
    print("（这个脚本只生成配置和做检查，不联网、不改任何外部系统）")
    print()
    ensure_config()
    check_env()
    check_files()

    print()
    print("=" * 62)
    if TODO:
        print("接下来做这几件：")
        for i, x in enumerate(TODO, 1):
            print("  %d. %s" % (i, x))
    else:
        print("配置齐全，可以直接跑：")
    print()
    print("  python3 scripts/selftest.py                 # 自检，全绿才继续")
    print("  python3 skills/amz-inventory-alert/scripts/run.py   # 库存预警")
    print("  python3 skills/amz-store-daily/scripts/run.py --shop <你的店>")
    print()
    print("数据从哪来：docs/DATA-SOURCES.md（领星/卖家精灵/SP-API 怎么接）")
    print("每天怎么用：docs/PLATFORM-GUIDE.md")
    print("=" * 62)
    if TODO and args.allow_incomplete:
        print("配置骨架已生成；--allow-incomplete 仅表示允许继续离线验收。")
        return 0
    return 0 if not TODO else 1


if __name__ == "__main__":
    raise SystemExit(main())
