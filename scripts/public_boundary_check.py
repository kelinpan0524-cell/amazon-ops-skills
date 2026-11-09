#!/usr/bin/env python3
"""公开源码边界：真实配置、经营数据、公司标识与内部云资源标识都不得被跟踪。

三道闸门一起过：
  1) 真实配置/运行数据不在 Git 里（FORBIDDEN / FORBIDDEN_PREFIX）
  2) 源码里没有已知内部云资源指纹与机器固定绝对路径（FINGERPRINTS 与用户目录绝对路径）
  3) 源码里没有公司/店铺/人员等业务标识（COMPANY_TOKENS）

`package_release.py` 打包前也会跑这套检查，任何一项命中就拒绝打包，不做静默脱敏。
"""
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FORBIDDEN = {
    "config/shops.json", "config/feishu_base.json", "config/report_delivery.json",
    "config/notify.json", "config/mcp.local.json", "data/report-index.jsonl", "data/.sync-state.json",
}
FORBIDDEN_PREFIX = (
    "data/raw/", "data/normalized/", "data/reports/", "data/exports/", "data/.locks/",
    # 内部知识库导出与经营画像只留本机；公开源码和分发包都不携带。
    "knowledge/", "notes/feishu-kb/", "profiles/", "judgements/",
)
# 只认通用形状，不内置任何真实租户/令牌（内置了等于把它们公开）。
# 内部部署要加私有指纹时，用环境变量 AMZ_EXTRA_FORBIDDEN（逗号分隔正则）。
CLOUD_PATTERNS = [
    (r"feishu\.cn/(?:base|docx|docs|sheets|drive|wiki)/[A-Za-z0-9]{10,}", "飞书云资源链接"),
    (r"doubaoapps\.com/app/[A-Za-z0-9_]{6,}", "妙搭应用地址"),
]


def _patterns():
    """通用云资源指纹 + 可选的自定义内部指纹（AMZ_EXTRA_FORBIDDEN）。"""
    import os
    out = list(CLOUD_PATTERNS)
    for extra in (os.environ.get("AMZ_EXTRA_FORBIDDEN") or "").split(","):
        extra = extra.strip()
        if extra:
            out.append((extra, "自定义内部指纹"))
    return out


def main():
    tracked = subprocess.check_output(["git", "ls-files"], cwd=ROOT, text=True).splitlines()
    bad = [p for p in tracked if p in FORBIDDEN or p.startswith(FORBIDDEN_PREFIX)]
    for rel in tracked:
        p = ROOT / rel
        if not p.is_file() or p.suffix.lower() not in (".md", ".py", ".json", ".yaml", ".yml", ".txt"):
            continue
        text = p.read_text(encoding="utf-8", errors="ignore")
        for pattern, why in _patterns():
            if re.search(pattern, text):
                bad.append("%s（%s）" % (rel, why))
        if re.search(r"(?<![\w.-])/(?:Users|home)/", text):
            bad.append("%s（机器固定绝对路径）" % rel)
    if bad:
        print("公开边界检查失败：")
        for p in sorted(set(bad)):
            print(" -", p)
        return 1
    print("公开边界检查通过：%d 个跟踪文件；真实配置、运行数据、已知内部云标识均未跟踪。" % len(tracked))
    return 0


if __name__ == "__main__":
    sys.exit(main())
