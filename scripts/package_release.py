#!/usr/bin/env python3
"""把技能包打成 zip 发给同事（不含任何公司数据/真实配置）。

用法：
  python3 scripts/package_release.py                 # 生成 dist/amz-ops-skills-<日期>.zip
  python3 scripts/package_release.py --out /tmp      # 指定输出目录

分发包只包含可公开的源码、文档和占位模板；真实配置、经营数据、
内部知识库导出与经营画像始终留在本机。给 zip 就是"解压 → 跑一次 setup → 能用"。

**打包时强制排除**（不做成可选项，防止手滑）：
  data/          任何数据（含真实销量、库存、评论）
  notes/         内部调研与飞书知识库导出
  config/*.json  真实配置（只放 *.example.json）
  .git/         历史里可能有旧配置

解压后同事要做的：跑一次 `python3 scripts/setup_local.py` 填自己的配置。
"""
import argparse
import datetime as dt
import os
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# 整目录排除
SKIP_DIRS = {"data", "notes", "archive", "dist", ".git", "__pycache__", ".mimosa",
             "judgements", "profiles"}
# 文件名模式排除
SKIP_FILES = {".DS_Store", ".cloud-file-tokens.json", ".sync-state.json",
              "mcp.local.json"}
# 真实配置：模板 + 通用预警规则可进包；店铺、云盘、Base、目标等真实配置不进包
CONFIG_ALLOW_SUFFIX = ".example.json"
CONFIG_PUBLIC_FILES = {"alert_rules.json"}
# 明确要带上的顶层内容
INCLUDE = ["README.md", "CHANGELOG.md", "CONTRIBUTING.md", "LICENSE", ".gitignore",
           "AGENTS.md", "skills", "scripts", "docs", "config",
           "system", "examples", "sources"]


def should_skip(path: Path) -> bool:
    rel = path.relative_to(ROOT)
    parts = set(rel.parts)
    if parts & SKIP_DIRS:
        return True
    if path.name in SKIP_FILES:
        return True
    if path.suffix in (".pyc", ".pyo"):
        return True
    # 真实业务数据永远不进包
    if path.suffix.lower() in (".csv", ".xlsx", ".xls", ".db", ".sqlite"):
        return True
    # config 下只放模板
    if rel.parts and rel.parts[0] == "config":
        if rel.name.endswith(CONFIG_ALLOW_SUFFIX):
            return False
        if rel.suffix == ".json" and "_example" not in rel.name and rel.name not in CONFIG_PUBLIC_FILES:
            # targets/shops/feishu_base/report_delivery 等业务配置不进包；通用预警规则例外
            return True
    return False


def collect():
    files = []
    for name in INCLUDE:
        p = ROOT / name
        if not p.exists():
            continue
        if p.is_file():
            if not should_skip(p):
                files.append(p)
            continue
        for f in p.rglob("*"):
            if f.is_file() and not should_skip(f):
                files.append(f)
    return sorted(set(files))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(ROOT / "dist"))
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    files = collect()
    total = sum(f.stat().st_size for f in files)
    print("打包 %d 个文件，共 %.1f MB" % (len(files), total / 1024 / 1024))
    for f in files[:8]:
        print("  ", f.relative_to(ROOT))
    if len(files) > 8:
        print("   …还有 %d 个" % (len(files) - 8))

    # 安全检查：确认包里没有真实配置和数据
    bad = [f for f in files
           if f.suffix.lower() in (".csv", ".xlsx", ".xls")
           or (f.parent.name == "config" and f.suffix == ".json"
               and not f.name.endswith(CONFIG_ALLOW_SUFFIX) and f.name not in CONFIG_PUBLIC_FILES)]
    if bad:
        print("\n!! 拒绝打包：以下文件不该进包")
        for f in bad:
            print("   ", f.relative_to(ROOT))
        return 1

    # 内容边界：宁可拒绝打包，也不把真实值替换后静默外发。
    # 真实店铺配置和经营数据已在 collect/should_skip 阶段排除；这里再阻断内部云标识。
    import re
    # 只认「云文档/表格/云盘资源 URL」这种通用形状，不内置任何真实租户或令牌值。
    # 内部部署要加自己的私有指纹时，放到环境变量 AMZ_EXTRA_FORBIDDEN（逗号分隔正则）。
    forbidden_patterns = [
        (r"feishu\.cn/(?:base|docx|docs|sheets|drive|wiki)/[A-Za-z0-9]{10,}", "飞书云资源链接"),
        (r"doubaoapps\.com/app/[A-Za-z0-9_]{6,}", "妙搭应用地址"),
        (r"(?<![\w.-])/(?:Users|home)/[\w.-]+/", "机器固定绝对路径"),
    ]
    for extra in (os.environ.get("AMZ_EXTRA_FORBIDDEN") or "").split(","):
        extra = extra.strip()
        if extra:
            forbidden_patterns.append((extra, "自定义内部指纹"))
    violations = []
    text_files = [f for f in files if f.suffix in (".md", ".py", ".json", ".yaml", ".yml", ".txt")]
    for f in text_files:
        try:
            text = f.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for pattern, why in forbidden_patterns:
            if re.search(pattern, text):
                violations.append((f.relative_to(ROOT), why))
    if violations:
        print("\n!! 拒绝打包：以下文件仍含内部标识，请回源码清理，不做静默脱敏")
        for rel, why in violations:
            print("   %-46s %s" % (rel, why))
        return 1
    print("\n内容边界：未发现已知内部云资源标识；不做静默替换。")

    if args.dry_run:
        print("\n[dry-run] 检查通过，没写文件")
        return 0

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = dt.date.today().strftime("%Y%m%d")
    dst = out_dir / ("amz-ops-skills-%s.zip" % stamp)
    with zipfile.ZipFile(dst, "w", zipfile.ZIP_DEFLATED) as z:
        for f in files:
            arc = f.relative_to(ROOT).as_posix()
            z.write(f, arc)
    print("\n✓ 生成 %s（%.1f MB）" % (dst, dst.stat().st_size / 1024 / 1024))
    print("  发给同事后让他们：解压 → python3 scripts/setup_local.py → 填配置")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
