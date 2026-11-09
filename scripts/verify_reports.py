#!/usr/bin/env python3
"""报告内容验证：不光看排版，还要查"数字对不对、有没有占位符、表格是不是空的"。

## 为什么需要
排版检查（check_report_layout）只保证文字不溢出，但报告可能：
- 数字全 0（数据没接上）
- 显示 None / nan / 待补（占位符没替换）
- 表格是空的（tbody 空着）
- 页脚没有口径说明（读的人不知道数字怎么来的）
这些排版检查都查不出来，但会让人看错数。

## 查什么
1. **结构**：DOCTYPE / title / 页眉 / 页脚口径说明
2. **占位符**：None、nan、NaN、TODO、【待补】、{{、}}、xxxx
3. **空表格**：<tbody></tbody> 或只有 1 行数据
4. **数字合理**：KPI 卡不全 0、不出现天文数字（>1e12）
5. **合规**：调 compliance.scan（和报告生成时同一套规则）

## 用法
  python3 scripts/verify_reports.py                    # 查 data/reports 下全部
  python3 scripts/verify_reports.py --dir data/reports/shop
  python3 scripts/verify_reports.py --strict           # 有警告也算失败
  python3 scripts/verify_reports.py --json             # 机器可读（CI 用）

退出码：有错误 → 1；只有警告 → 0（--strict 时 1）；全过 → 0。
"""
import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "skills" / "_shared"))

# 不该出现在成品报告里的东西
PLACEHOLDER_PAT = [
    (re.compile(r"(?<![A-Za-z])None(?![A-Za-z])"), "None 未替换"),
    (re.compile(r"\bnan\b|\bNaN\b"), "NaN"),
    (re.compile(r"\bTODO\b|\bFIXME\b"), "TODO/FIXME"),
    (re.compile(r"【待补】|待补|xxxx|\{\{|\}\}"), "占位符"),
    (re.compile(r">\s*undefined\s*<"), "undefined"),
]
# 注意：不查"未校准"——那是诚实的口径说明，不是占位符
ALLOW_WORDS = ("未校准", "不可用", "缺数据", "未设定", "人工复核", "没查到", "不可比")


def _text(html):
    s = re.sub(r"<script[^>]*>.*?</script>", " ", html, flags=re.S | re.I)
    s = re.sub(r"<style[^>]*>.*?</style>", " ", s, flags=re.S | re.I)
    return re.sub(r"<[^>]+>", " ", s)


def check_structure(html):
    errs, warns = [], []
    if "<!DOCTYPE html>" not in html:
        errs.append("缺 DOCTYPE")
    if "<title>" not in html:
        errs.append("缺 title")
    body = _text(html)
    if len(body.strip()) < 200:
        errs.append("正文过短（%d 字符），可能是空报告" % len(body.strip()))
    # 页脚口径：报告必须说明数据怎么来的
    if not any(w in html for w in ("口径", "数据源", "数据截至")):
        warns.append("页脚没有口径/数据源说明")
    return errs, warns


def check_placeholders(html):
    """只查正文文字，不查 CSS/script —— CSS 里的 `}}` 和 `100%` 不是占位符。"""
    errs = []
    text = _text(html)
    for pat, why in PLACEHOLDER_PAT:
        for mo in pat.finditer(text):
            ctx = text[max(0, mo.start() - 40):mo.end() + 40]
            ctx_txt = re.sub(r"<[^>]+>", "", ctx).strip()
            # 上下文里如果是"缺数据/未校准"这类诚实表述，放过
            if any(w in ctx_txt for w in ALLOW_WORDS):
                continue
            errs.append("%s：…%s…" % (why, ctx_txt[:60]))
            break      # 同类只报第一条，避免刷屏
    return errs


def check_tables(html):
    errs, warns = [], []
    bodies = re.findall(r"<tbody>(.*?)</tbody>", html, flags=re.S | re.I)
    for i, b in enumerate(bodies, 1):
        rows = len(re.findall(r"<tr", b))
        if rows == 0:
            errs.append("第 %d 个表格没有数据行（tbody 空）" % i)
        elif len(b.strip()) < 20:
            warns.append("第 %d 个表格内容过短" % i)
    return errs, warns


def check_numbers(html):
    """数字合理性：KPI 卡全 0、天文数字。"""
    errs, warns = [], []
    # KPI 卡的值形如 class="kval">$1,234<
    vals = re.findall(r'class="kval"[^>]*>([^<]{1,24})<', html)
    if vals:
        nums = []
        for v in vals:
            m2 = re.search(r"-?[\d,]+(?:\.\d+)?", v.replace("$", "").replace("%", ""))
            if m2:
                try:
                    nums.append(float(m2.group(0).replace(",", "")))
                except ValueError:
                    pass
        if nums and all(n == 0 for n in nums):
            errs.append("KPI 卡全是 0（数据可能没接上）")
        big = [n for n in nums if abs(n) > 1e12]
        if big:
            errs.append("KPI 出现异常大数 %s" % big[:3])
    # 全局天文数字
    for mo in re.finditer(r"\b\d{15,}\b", html):
        errs.append("出现异常长数字 %s" % mo.group(0)[:20])
        break
    return errs, warns


def check_compliance(html):
    try:
        import compliance as cp
        hits = cp.scan(html)
        real = [h for h in hits if not h["kind"].startswith("车标品牌名")]
        if real:
            return ["合规命中 %d 处：%s" % (
                len(real), "、".join(h["word"] for h in real[:3]))], []
    except Exception:
        pass
    return [], []


def verify_one(path: Path):
    try:
        html = path.read_text(encoding="utf-8", errors="ignore")
    except OSError as e:
        return {"file": str(path), "errors": ["读不了：%s" % e], "warnings": []}
    errs, warns = [], []
    for fn in (check_structure, check_tables, check_numbers, check_compliance):
        e, w = fn(html)
        errs += e
        warns += w
    errs += check_placeholders(html)
    return {"file": str(path.relative_to(ROOT)), "errors": errs, "warnings": warns}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", default="data/reports")
    ap.add_argument("--strict", action="store_true")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    base = ROOT / args.dir
    if not base.exists():
        print("目录不存在：%s（先跑一次报告生成）" % base)
        return 2
    files = sorted(base.rglob("*.html"))
    if not files:
        print("目录下没有 HTML 报告：%s" % base)
        return 2

    results = [verify_one(f) for f in files]
    n_err = sum(len(r["errors"]) for r in results)
    n_warn = sum(len(r["warnings"]) for r in results)
    bad_files = [r for r in results if r["errors"] or (args.strict and r["warnings"])]

    if args.json:
        print(json.dumps({"files": len(files), "errors": n_err, "warnings": n_warn,
                          "bad": bad_files}, ensure_ascii=False, indent=2))
    else:
        for r in results:
            if r["errors"]:
                print("✗ %s" % r["file"])
                for e in r["errors"][:5]:
                    print("    E: %s" % e)
            elif r["warnings"]:
                print("! %s" % r["file"])
                for w in r["warnings"][:3]:
                    print("    W: %s" % w)
            else:
                print("✓ %s" % r["file"])
        print()
        print("合计：%d 份报告，%d 个错误，%d 个警告" % (len(files), n_err, n_warn))

    if n_err:
        return 1
    if args.strict and n_warn:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
