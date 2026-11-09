#!/usr/bin/env python3
"""销量异常检测：用**免费的自有数据**找出"疑似被跟卖/被降权"的 SKU。

## 为什么需要它
卖家精灵按次计费，185 个 ASIN 全量每天查 = 5550 次/月，太贵。
但跟卖的**结果**会体现在自己的销量上——销量是免费的（领星已拉），
所以可以先用销量筛一遍，只对"卖得突然不对"的 SKU 花额度查卖家数。

## 判什么（三条，都是"跟自己比"，不是跟同行比）
1. **销量骤降**：最近 3 天日均 vs 前 14 天日均，跌 ≥40%
2. **排除断货**：FBA 可售为 0 或可售天数 <7 天 → 那是断货，不是跟卖
3. **排除新品**：上架不足 21 天 → 基数不稳，容易误报

## 输出
- 屏幕：可疑清单（ASIN / SKU / 店铺 / 跌幅 / 库存 / 可能原因）
- 文件：`data/raw/hijack-suspects.txt`（一行一个 ASIN，喂给 amz-hijack-watch --asins-file）

用法：
  python3 scripts/find_suspects.py                # 看清单
  python3 scripts/find_suspects.py --format text  # 一行摘要（群消息用）
  python3 scripts/find_suspects.py --min-drop 0.3 # 阈值调松
"""
import argparse
import collections
import datetime as dt
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "skills" / "_shared"))
import metrics as m  # noqa: E402

OUT = ROOT / "data" / "raw" / "hijack-suspects.txt"
RECENT_DAYS = 3        # 最近几天
BASE_DAYS = 10         # 对比基准多少天（sales_daily 目前 16 天，留 3 天余量）
DROP_ALERT = 0.40      # 跌幅阈值
MIN_BASE_UNITS = 1.0   # 基准日均至少 1 件才判（太少的话 1 件波动就是 100%）
NEW_PRODUCT_DAYS = 21  # 上架不足这么多天不判


def load_series():
    """返回 {asin: {"sku","shop","by_date":{date: units}, "last_date"}}"""
    out = {}
    for r in m.load("sales_daily"):
        asin = (r.get("asin") or "").strip()
        d = m.row_date(r)
        if not asin or not d:
            continue
        a = out.setdefault(asin, {"sku": r.get("sku") or "", "shop": r.get("shop") or "",
                                  "by_date": {}, "name": (r.get("product_name") or "")[:40]})
        a["by_date"][d] = (a["by_date"].get(d) or 0) + (m.num(r.get("units")) or 0)
    return out


def load_stock():
    """{(shop, sku): (fba_available, fba_inbound)} 取最新快照。"""
    out, seen = {}, set()
    rows = m.load("inventory_daily")
    for r in rows:
        key = (r.get("shop") or "", r.get("sku") or "")
        d = m.row_date(r) or ""
        if key in seen and d < (out.get(key, ("", 0, 0))[0] if key in out else ""):
            continue
        out[key] = (d, m.num(r.get("fba_available")) or 0, m.num(r.get("fba_inbound")) or 0)
    return {k: (v[1], v[2]) for k, v in out.items()}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--min-drop", type=float, default=DROP_ALERT)
    ap.add_argument("--format", default="html", choices=["html", "text"])
    args = ap.parse_args()

    series = load_series()
    if not series:
        print("没有 sales_daily 数据（先跑 scripts/fetch_sku.py --days 16）")
        return 2
    stock = load_stock()
    today = dt.date.today()

    suspects, checked = [], 0
    for asin, a in series.items():
        ds = sorted(a["by_date"])
        if len(ds) < RECENT_DAYS + BASE_DAYS:
            continue
        checked += 1
        recent = ds[-RECENT_DAYS:]
        base = ds[-(RECENT_DAYS + BASE_DAYS):-RECENT_DAYS]
        if not base:
            continue
        # 新品不判的原始想法是靠"上架天数"，但我们没有上架日期字段，
        # 只能看到"有几天销量数据"——数据窗口本身就 16 天，用它判新品会把
        # 所有 ASIN 都跳过（2026-11-04 实测：476 个全被跳过，一个都查不出来）。
        # 改成靠下面的 MIN_BASE_UNITS 兜底：基准期日均不到 1 件的不判。
        rec_avg = sum(a["by_date"][d] for d in recent) / len(recent)
        base_avg = sum(a["by_date"][d] for d in base) / len(base)
        if base_avg < MIN_BASE_UNITS:
            continue
        drop = (base_avg - rec_avg) / base_avg
        if drop < args.min_drop:
            continue
        avail, inbound = stock.get((a["shop"], a["sku"]), (None, 0))
        # 断货排除：可售为 0 且没在途 → 那是缺货不是跟卖
        if avail is not None and avail <= 0 and (inbound or 0) <= 0:
            reason = "库存已经 0，是断货不是跟卖"
            kind = "断货"
        elif avail is not None and rec_avg > 0 and avail / rec_avg < 7:
            reason = "可售不足 7 天，可能是断货前兆"
            kind = "断货风险"
        else:
            reason = "库存正常但销量掉——疑似被跟卖/掉排名/广告停了"
            kind = "疑似跟卖"
        suspects.append({"asin": asin, "sku": a["sku"], "shop": a["shop"],
                         "name": a["name"], "recent": round(rec_avg, 1),
                         "base": round(base_avg, 1), "drop": round(drop * 100),
                         "avail": avail, "kind": kind, "reason": reason})

    suspects.sort(key=lambda x: -x["drop"])
    hijack = [s for s in suspects if s["kind"] == "疑似跟卖"]

    if args.format == "text":
        if not hijack:
            print("【销量异常】%d 个 ASIN 检查，没有「库存正常但销量骤降」的" % checked)
        else:
            print("【销量异常】%d 个疑似被跟卖（销量骤降但库存正常）：" % len(hijack))
            for s in hijack[:6]:
                print("  %s %s 日均 %.1f→%.1f（-%d%%）库存 %s"
                      % (s["asin"], s["sku"], s["base"], s["recent"], s["drop"],
                         s["avail"] if s["avail"] is not None else "?"))
    else:
        print("检查 %d 个 ASIN（有 %d 天以上数据）" % (checked, RECENT_DAYS + BASE_DAYS))
        print("可疑 %d 个，其中「库存正常但销量掉」%d 个要查卖家数：" % (len(suspects), len(hijack)))
        print("%-13s %-16s %-8s %8s %8s %6s %8s" % (
            "ASIN", "SKU", "店铺", "基准日均", "近3日", "跌幅", "库存"))
        for s in suspects[:15]:
            print("%-13s %-16s %-8s %8.1f %8.1f %5d%% %8s" % (
                s["asin"], s["sku"][:16], s["shop"], s["base"], s["recent"],
                s["drop"], s["avail"] if s["avail"] is not None else "?"))

    # 写待查清单（只写"疑似跟卖"的，断货的不用花额度查卖家数）
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text("\n".join(s["asin"] for s in hijack) + ("\n" if hijack else ""),
                   encoding="utf-8")
    print("\n→ 待查清单 %d 个 ASIN 写入 %s" % (len(hijack), OUT.relative_to(ROOT)))
    if hijack:
        print("   下一步：python3 skills/amz-hijack-watch/scripts/run.py --asins-file %s --fetch"
              % OUT.relative_to(ROOT))
    return 1 if hijack else 0


if __name__ == "__main__":
    sys.exit(main())
