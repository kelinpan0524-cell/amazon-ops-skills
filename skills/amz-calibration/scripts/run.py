#!/usr/bin/env python3
"""每周校准：把到期判断拉出来对账，算命中率，给出降权/沉淀建议。

它自己不取数（取不到），只做三件事：
1. 列出到期该复核的判断（status: open 且 review_on ≤ 今天）
2. 统计每个技能的历史命中率（confirmed / (confirmed+refuted)）
3. 命中率低于阈值就建议降权，连续被证实三次的规则建议升级为画像事实

判断文件放 judgements/YYYY-MM-DD-<域>.md，格式见 system/ARCHITECTURE.md。
"""
import datetime as dt
import glob
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "_shared"))
import metrics as m  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
JUDGE_DIR = os.environ.get("AMZ_JUDGE_DIR") or os.path.join(ROOT, "judgements")
T = m.load_thresholds()["calibration"]


def parse_front_matter(path):
    """极简 front-matter 解析：只认 key: value，够用且无依赖。"""
    data = {}
    try:
        with open(path) as f:
            text = f.read()
    except OSError:
        return data
    if not text.startswith("---"):
        return data
    body = text.split("---", 2)[1]
    for line in body.splitlines():
        if ":" in line:
            k, v = line.split(":", 1)
            data[k.strip()] = v.strip()
    return data


def main():
    files = sorted(glob.glob(os.path.join(JUDGE_DIR, "*.md")))
    files = [f for f in files if os.path.basename(f) != "README.md"]
    if not files:
        print("【结论】judgements/ 里还没有判断记录。每次诊断出的结论都要写一条，否则没法对账。")
        print("  模板：\n---\nid: J-YYYYMMDD-01\nskill: amz-ads-diagnose\nstatus: open\nexpected: \"改标题后 14 天会话 +10%\"\nreview_on: 2026-11-18\n---")
        return

    today = dt.date.today().isoformat()
    due, stats = [], {}
    for f in files:
        d = parse_front_matter(f)
        skill = d.get("skill", "未标注")
        st = d.get("status", "open")
        s = stats.setdefault(skill, {"confirmed": 0, "refuted": 0, "open": 0})
        if st == "open":
            s["open"] += 1
            if d.get("review_on", "9999-99-99") <= today:
                due.append((d.get("review_on", ""), d.get("id", os.path.basename(f)), skill, d.get("expected", "")))
        elif st == "confirmed":
            s["confirmed"] += 1
        elif st == "refuted":
            s["refuted"] += 1

    print("【到期待复核】%d 条" % len(due))
    for rv, jid, skill, exp in sorted(due):
        print("  - %s（%s，%s）预期：%s" % (jid, skill, rv, exp))
    if due:
        print("  做法：用真实数据核对 → 把文件里的 status 改成 confirmed 或 refuted → 写一句结论。")

    print("\n【命中率】")
    if not stats:
        print("  还没有已结案的判断。")
    for skill, s in sorted(stats.items()):
        closed = s["confirmed"] + s["refuted"]
        if closed == 0:
            print("  %-22s 未结案 %d 条" % (skill, s["open"]))
            continue
        rate = s["confirmed"] / closed
        flag = ""
        if rate < T["min_hit_rate"]:
            flag = "  ← 低于 %.0f%%，建议降为只观察不建议" % (T["min_hit_rate"] * 100)
        elif s["confirmed"] >= T["confirm_hits_to_promote"]:
            flag = "  ← 连续证实，可沉淀为画像事实"
        print("  %-22s 命中 %.0f%%（证实 %d / 推翻 %d，未结 %d）%s"
              % (skill, rate * 100, s["confirmed"], s["refuted"], s["open"], flag))

    print("\n【阈值】改动只能改 config/thresholds.yaml，并在 config/CHANGELOG.md 记一行（改什么、为什么、依据哪条判断）。")


if __name__ == "__main__":
    main()
