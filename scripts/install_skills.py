#!/usr/bin/env python3
"""把本仓库的技能挂到各家 Agent 的技能目录（软链，改仓库即生效）。

各家读技能的位置（已核实）：
  Codex       ~/.agents/skills/       （也可放项目内 .agents/skills/）
  Claude Code ~/.claude/skills/
  Trae        手动在设置里指向目录（脚本给路径）
  WorkBuddy   市场/导入包（用 --pack 打 zip）
  豆包         拖文件夹导入（用 --pack 打 zip）

用法：
  python3 scripts/install_skills.py --list
  python3 scripts/install_skills.py --target agents,claude
  python3 scripts/install_skills.py --pack ~/Desktop/amz-skills.zip
  python3 scripts/install_skills.py --target agents --uninstall
"""
import argparse
import os
import sys
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SKILLS = os.path.join(ROOT, "skills")

TARGETS = {
    "agents": os.path.expanduser("~/.agents/skills"),
    "claude": os.path.expanduser("~/.claude/skills"),
}


def skill_dirs():
    out = []
    for name in sorted(os.listdir(SKILLS)):
        p = os.path.join(SKILLS, name)
        if name.startswith("_") or not os.path.isdir(p):
            continue
        if os.path.exists(os.path.join(p, "SKILL.md")):
            out.append((name, p))
    return out


def link(name, src, dst_dir, dry):
    dst = os.path.join(dst_dir, name)
    if os.path.islink(dst) or os.path.exists(dst):
        return "exists"
    if dry:
        return "link"
    os.makedirs(dst_dir, exist_ok=True)
    os.symlink(src, dst)
    return "linked"


def unlink(name, dst_dir, dry):
    dst = os.path.join(dst_dir, name)
    if os.path.islink(dst):
        if not dry:
            os.unlink(dst)
        return "removed"
    if os.path.exists(dst):
        return "skip-not-link"   # 真目录，不动
    return "missing"


def pack(path, dry):
    if dry:
        print("将打包到 %s" % path)
        return
    target_path = os.path.expanduser(path)
    parent = os.path.dirname(os.path.abspath(target_path))
    os.makedirs(parent, exist_ok=True)
    with zipfile.ZipFile(target_path, "w", zipfile.ZIP_DEFLATED) as z:
        # _shared 必须一起打包：所有 amz-* 的 run.py 都 import metrics，缺了装机即坏
        shared_dir = os.path.join(SKILLS, "_shared")
        for dirpath, _, files in os.walk(shared_dir):
            if "__pycache__" in dirpath:
                continue
            for f in files:
                if f.endswith(".pyc"):
                    continue
                full = os.path.join(dirpath, f)
                z.write(full, os.path.relpath(full, SKILLS))
        for name, src in skill_dirs():
            for dirpath, _, files in os.walk(src):
                if "__pycache__" in dirpath:
                    continue
                for f in files:
                    if f.endswith(".pyc"):
                        continue
                    full = os.path.join(dirpath, f)
                    rel = os.path.relpath(full, SKILLS)
                    z.write(full, rel)
    print("✓ 打包完成：%s（含 %d 个技能）" % (path, len(skill_dirs())))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--target", default="", help="agents,claude 逗号分隔")
    ap.add_argument("--uninstall", action="store_true")
    ap.add_argument("--pack", default="", help="打 zip 给豆包/WorkBuddy")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    skills = skill_dirs()
    if args.list or (not args.target and not args.pack):
        print("本仓库技能 %d 个：" % len(skills))
        for name, _ in skills:
            print("  - " + name)
        print("\n可挂载位置：")
        for k, v in TARGETS.items():
            print("  %-8s %s%s" % (k, v, "" if os.path.isdir(v) else "（目录不存在，会自动建）"))
        print("\n用法：--target agents,claude | --pack ~/Desktop/amz.zip | --uninstall")
        return

    if args.pack:
        pack(args.pack, args.dry_run)
        return

    targets = [t.strip() for t in args.target.split(",") if t.strip()]
    unknown = [t for t in targets if t not in TARGETS]
    if unknown:
        sys.exit("不认识的 target：%s" % unknown)

    for t in targets:
        d = TARGETS[t]
        print("[%s] %s" % (t, d))
        for name, src in skills:
            if args.uninstall:
                r = unlink(name, d, args.dry_run)
            else:
                r = link(name, src, d, args.dry_run)
            if r != "exists":
                print("  %-26s %s" % (name, r))

    if not args.uninstall:
        print("\n挂载完成。各家怎么调（细节见 docs/CLIENTS.md）：")
        print("  Codex / Claude Code / ZCode：说需求即可，按 SKILL.md 的 description 自动匹配")
        print("  Codex 也可以显式：$amz-ads-diagnose")
        print("  Trae：设置里把技能目录指到本仓库的 skills/（或挂好的 ~/.agents/skills）")
        print("  WorkBuddy / 豆包：用 --pack 打成 zip 再导入（它们不读目录）")
        print("  飞书机器人等「没有 terminal」的客户端：脚本跑不了，只能用纯 MCP 的 4 个技能")
        print("  凭证：环境变量优先；GUI 客户端拿不到 shell 变量时填 config/mcp.local.json")
        print("  注意：技能要读 data/ 与 config/，这些在仓库里，**不要把仓库目录挪走**")


if __name__ == "__main__":
    main()
