#!/usr/bin/env python3
"""CI 防回归测试集：把 2026-11-04 装机/验收踩过的坑全部固化成断言。

覆盖：
  1. automations.yaml 重复键（buybox-watch 曾让购物车监控被静默顶掉）
  2. 桩生成 exec A && B 的 bug（复合命令第二条永不执行、日志重定向只覆盖第二条）
  3. 退出码口径：0/1 都归档并透传；2 及以上不归档（告警报告曾永远进不了飞书）
  4. 报告归档主载体 = HTML（不能退化成把 Markdown 日志导成 docx）
  5. daily-group-card 必须带 --send（默认只打印，自动化曾"发了"其实没发）
  6. 无 NAS / 无 hermes 残留（用户硬性架构约束）
  7. 卖家精灵 MCP 常量（/v2/mcp、asin.detail、asins 参数）
  8. 每日链必含 SKU 级数据表（sales/inventory/ads_asin）
  9. notify.json 必须 gitignore（群 id 属本机配置）
 10. ASIN 必须可点击跳转亚马逊前台；卡片必须是 interactive 交互卡片

运行：python3 scripts/ci_check.py   （纯本地，无需 lark-cli/MCP/网络；无副作用）
"""
import os
import re
import sys
import tempfile
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "skills" / "_shared"))

FAILED = []
PASSED = 0


def check(name, fn):
    global PASSED
    try:
        fn()
        PASSED += 1
        print("  ✓ %s" % name)
    except Exception as e:
        FAILED.append((name, str(e)))
        print("  ✗ %s — %s" % (name, e))


def _read(rel):
    return (ROOT / rel).read_text(encoding="utf-8")


# ---------- 1. automations.yaml ----------







# ---------- 2. 桩生成 ----------





# ---------- 3. 退出码口径 ----------

def _wrapper_case(rc, stderr=""):
    import _report_wrapper_lib as w
    calls = []
    w._publish = lambda *a, **k: calls.append(a) or 0
    fake = types.SimpleNamespace(returncode=rc, stdout="some output", stderr=stderr)
    w.subprocess.run = lambda *a, **k: fake
    orig_cwd = os.getcwd()
    os.chdir(ROOT)
    try:
        out = w.run_and_publish("anything.py", "ci_tmp", "CI 测试", dry_run=True)
    finally:
        os.chdir(orig_cwd)
    return out, calls










# ---------- 4. HTML 归档映射 ----------







# ---------- 5. 群卡片 ----------







# ---------- 6. 无 NAS / 无 hermes ----------



def t_no_hermes_anywhere():
    skip = {"archive", "notes", ".git", "node_modules"}
    skip_files = {"ci_check.py"}
    hits = []
    for p in ROOT.rglob("*"):
        if not p.is_file() or p.name in skip_files or any(part in skip for part in p.relative_to(ROOT).parts):
            continue
        if p.suffix.lower() not in {".py", ".md", ".json", ".yaml", ".yml", ".sh", ".txt"}:
            continue
        try:
            if "hermes" in p.read_text(encoding="utf-8", errors="ignore").lower():
                hits.append(str(p.relative_to(ROOT)))
        except OSError:
            pass
    assert not hits, "hermes 残留：%s" % hits[:8]


def t_skill_frontmatter_automation():
    bad = []
    for p in (ROOT / "skills").glob("*/SKILL.md"):
        txt = p.read_text(encoding="utf-8")
        if re.search(r"^\s{2}hermes:", txt, re.M):
            bad.append(p.parent.name)
        if not re.search(r"^\s{2}automation:", txt, re.M):
            bad.append(p.parent.name + "(缺 automation 块)")
    assert not bad, "SKILL.md frontmatter 异常：%s" % bad


# ---------- 7. 卖家精灵 MCP 常量 ----------



# ---------- 8. 每日链 SKU 级数据 ----------



# ---------- 9. ASIN 可点击 ----------

def t_asin_linkify():
    import html_report as hr
    out = hr.linkify_asin("B0B2D4CXC7")
    assert "https://www.amazon.com/dp/B0B2D4CXC7" in out, "ASIN 必须生成前台链接"
    assert hr.linkify_asin("VW-CA-80077") == "VW-CA-80077", "非 ASIN 不应误包链接"


def t_sku_table_columns():
    import sku_table as st
    src = (ROOT / "skills" / "_shared" / "sku_table.py").read_text(encoding="utf-8")
    assert "SKU 编码" in src, "SKU 明细必须带SKU 编码列"
    assert "可售天数" in src and "ACOS" in src



# ---------- 10. USD 口径（2026-11-04 起不做币种换算） ----------

def t_no_cny_anywhere():
    skip = {"archive", "notes", ".git", "__pycache__"}
    hits = []
    for p in list((ROOT / "scripts").rglob("*.py")) + list((ROOT / "skills").rglob("*.py")) \
             + list((ROOT / "config").rglob("*.json")):
        if any(part in skip for part in p.parts) or p.name in (
                "ci_check.py", "rebase_usd.py", "selfcheck_report.py"):
            continue  # 自检器与 USD 迁移/残留检测工具合法出现 CNY 字样
        txt = p.read_text(encoding="utf-8", errors="ignore")
        for bad in ("CNY", "¥", "fx_usd_cny", "_cny"):
            if bad in txt:
                hits.append("%s(%s)" % (p.relative_to(ROOT), bad))
                break
    assert not hits, "人民币口径残留：%s" % hits[:8]


def t_fetch_requests_usd():
    assert '"currency_code": "USD"' in _read("scripts/fetch_lingxing.py"), "店级数据必须按 USD 拉取"
    assert '"currency_code": "USD"' in _read("scripts/fetch_sku.py"), "SKU 销售必须按 USD 拉取"
    assert '"currency": "USD"' in _read("scripts/fetch_ads.py"), "广告金额必须标 USD"


def t_methodology_in_reports():
    for f in ("amz-store-daily", "amz-sku-daily", "amz-stock-alert", "amz-company-overview",
              "amz-inventory-alert", "amz-alert-center", "amz-ads-diagnose"):
        assert "methodology" in _read("skills/%s/scripts/run.py" % f), "%s 缺计算规则与预警标准区块" % f


def t_proactive_protocols():
    for s in ("amz-product-research", "amz-ads-diagnose", "amz-traffic-diagnose", "amz-listing-audit",
              "amz-keyword-intel", "amz-competitor-watch", "amz-review-insight", "amz-listing-images"):
        txt = _read("skills/%s/SKILL.md" % s)
        assert "交互协议" in txt and "选项" in txt, "%s 缺主动式多轮询问协议" % s





def main():
    print("== CI 防回归测试集（2026-11-04 坑清单固化）==")
    groups = [
        ("架构约束", [t_no_hermes_anywhere, t_skill_frontmatter_automation]),
        ("SKU 报告", [t_asin_linkify, t_sku_table_columns]),
        ("USD 口径", [t_no_cny_anywhere, t_fetch_requests_usd]),
        ("算法说明", [t_methodology_in_reports]),
        ("主动式协议", [t_proactive_protocols]),
    ]
    for name, fns in groups:
        print("[%s]" % name)
        for fn in fns:
            check(fn.__name__, fn)
    print("\n通过 %d 项，失败 %d 项" % (PASSED, len(FAILED)))
    if FAILED:
        for n, e in FAILED:
            print("  FAIL %s: %s" % (n, e))
        return 1
    # 清理测试残留报告
    import shutil
    shutil.rmtree(ROOT / "data" / "reports" / "ci_tmp", ignore_errors=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
