#!/usr/bin/env python3
"""利润复盘（周报/月报）：毛利率、亏损 ASIN、分店对比、趋势。

## 跟总览里的「毛利情况」有什么不同
总览里那块是**当天快照**（给管理层每天扫一眼）；
这个报告是**周/月复盘**——看趋势、看亏损榜、看哪个店在恶化。

## 口径（必读，不然会看错）
- 数据来自领星利润报表（`gross_profit` 已扣采购成本 + FBA 配送费 + 佣金）
- **不含头程物流**（实测 `proportion_of_cg_transport` 恒为 0）→ 这是**上限值**
- **只统计录了采购成本的 ASIN**（`has_cost=1`）：把"没录"当"成本 0"会让毛利率虚高
- 覆盖率会写在报告里（现在约 25%），别拿它当全店口径

用法：
  python3 skills/amz-profit-review/scripts/run.py --period week
  python3 skills/amz-profit-review/scripts/run.py --period month --anchor 2026-10
  python3 skills/amz-profit-review/scripts/run.py --period week --format text

退出码：有亏损 ASIN → 1；否则 0；没数据 → 2。
"""
import argparse
import calendar
import datetime as dt
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent.parent / "_shared"))
import benchmarks as bm   # noqa: E402
import chartlets as c     # noqa: E402
import html_report as hr  # noqa: E402
import metrics as m       # noqa: E402

ROOT = HERE.parent.parent.parent
OUT_DIR = ROOT / "data" / "reports" / "profit"


def num(v, d=0.0):
    n = m.num(v)
    return d if n is None else n


def load():
    rows = m.load("profit_daily")
    out = []
    for r in rows:
        d = m.row_date(r)
        if not d:
            continue
        out.append({"date": d, "shop": r.get("shop") or "",
                    "asin": r.get("asin") or "", "sku": r.get("sku") or "",
                    "name": (r.get("item_name") or "")[:50],
                    "rev": num(r.get("revenue")), "gp": num(r.get("gross_profit")),
                    "has_cost": num(r.get("has_cost")),
                    "price": num(r.get("avg_purchase_cost"))})
    return out


def window(rows, start, end):
    lo, hi = start.isoformat(), end.isoformat()
    return [r for r in rows if lo <= r["date"] <= hi]


def agg(rows, key=None):
    """汇总。key=None 总体，key='shop' 分店。只算 has_cost=1。"""
    use = [r for r in rows if r["has_cost"] > 0]
    # n_all 用"本期总行数"，不是"有销售额的行数"——
    # 有些行只有成本没有销售额（退货/费用），按 rev>0 筛会出现 190/183 分子大于分母
    total_all = len(rows)
    if key is None:
        rev = sum(r["rev"] for r in use)
        gp = sum(r["gp"] for r in use)
        neg = [r for r in use if r["gp"] < 0]
        return {"rev": rev, "gp": gp, "margin": (gp / rev) if rev else None,
                "n": len(use), "n_all": total_all, "neg": neg}
    out = {}
    for r in use:
        b = out.setdefault(r[key] or "?", {"rev": 0.0, "gp": 0.0, "n": 0, "neg": []})
        b["rev"] += r["rev"]
        b["gp"] += r["gp"]
        b["n"] += 1
        if r["gp"] < 0:
            b["neg"].append(r)
    for b in out.values():
        b["margin"] = (b["gp"] / b["rev"]) if b["rev"] else None
    return out


def merge_neg(rows):
    """按 (店, ASIN) 合并亏损行，按亏损额升序。

    数据是按天的，不合并同一个 ASIN 会在月榜里出现好几次
    （2026-11-04 实测：月度亏损 23 条 → 合并后 16 个 ASIN）。
    """
    m2 = {}
    for r in rows:
        k = (r["shop"], r["asin"])
        e = m2.get(k)
        if not e:
            m2[k] = dict(r)
        else:
            e["rev"] += r["rev"]
            e["gp"] += r["gp"]
            if r.get("price"):
                e["price"] = r["price"]
    return sorted(m2.values(), key=lambda r: r["gp"])


def period_bounds(period, anchor):
    """返回 (本期起, 本期止, 上期起, 上期止, 标签, 上期标签)。"""
    if period == "week":
        d = anchor or dt.date.today()
        monday = d - dt.timedelta(days=d.weekday())
        start, end = monday, monday + dt.timedelta(days=6)
        p_start, p_end = start - dt.timedelta(days=7), end - dt.timedelta(days=7)
        return (start, end, p_start, p_end,
                "%s ~ %s" % (start.isoformat(), end.isoformat()),
                "%s ~ %s" % (p_start.isoformat(), p_end.isoformat()))
    # month
    d = anchor or dt.date.today()
    y, mo = d.year, d.month
    start = dt.date(y, mo, 1)
    end = dt.date(y, mo, calendar.monthrange(y, mo)[1])
    pm, py = (mo - 1, y) if mo > 1 else (12, y - 1)
    p_start = dt.date(py, pm, 1)
    p_end = dt.date(py, pm, calendar.monthrange(py, pm)[1])
    return (start, end, p_start, p_end, "%d-%02d" % (y, mo), "%d-%02d" % (py, pm))


def render(res, prev_res, by_shop, prev_by_shop, label, p_label, period):
    th = bm.load_targets().get("profit") or {}
    tgt = th.get("gross_margin_target") or 0.30
    floor = th.get("gross_margin_floor") or 0.15

    negs = merge_neg(res["neg"])
    prev_negs = merge_neg(prev_res["neg"])

    mg, pmg = res["margin"], prev_res["margin"]
    delta = (mg - pmg) * 100 if (mg is not None and pmg is not None) else None
    cards = [
        {"label": "销售额", "value": "$%s" % format(int(res["rev"]), ","),
         "note": "只算有采购成本的 %d/%d 个 ASIN" % (res["n"], res["n_all"])},
        {"label": "毛利", "value": "$%s" % format(int(res["gp"]), ",")},
        {"label": "毛利率", "value": ("%.1f%%" % (mg * 100)) if mg is not None else "缺数据",
         "note": ("目标 %.0f%% · 上期 %.1f%%（%+.1f 个点）"
                  % (tgt * 100, pmg * 100, delta)) if (pmg is not None and delta is not None)
                 else "目标 %.0f%%" % (tgt * 100)},
        {"label": "亏损 ASIN", "value": str(len(negs)),
         "note": "上期 %d 个" % len(prev_negs)},
    ]

    # 分店
    trs = []
    for shop, b in sorted(by_shop.items(), key=lambda kv: -kv[1]["rev"]):
        pb = prev_by_shop.get(shop) or {}
        d_margin = ((b["margin"] - pb["margin"]) * 100
                    if (b.get("margin") is not None and pb.get("margin") is not None) else None)
        badge = "—"
        if b["margin"] is not None:
            if b["margin"] < 0:
                badge = '<span class="tag bad">整店亏损</span>'
            elif b["margin"] < floor:
                badge = '<span class="tag warn">偏低</span>'
            elif b["neg"]:
                badge = '<span class="tag warn">%d 个亏损</span>' % len(b["neg"])
            else:
                badge = '<span class="tag good">正常</span>'
        trs.append([shop, str(b["n"]), "$%s" % format(int(b["rev"]), ","),
                    "$%s" % format(int(b["gp"]), ","),
                    ("%.1f%%" % (b["margin"] * 100)) if b["margin"] is not None else "-",
                    ("%+.1f" % d_margin) if d_margin is not None else "-",
                    str(len(b["neg"])), badge])

    # 亏损明细：**全部列出**，按店分组（运营只看自己那份，老板看合计）
    # 关键：先按 (店, ASIN) 合并——数据是按天的，不合并同一个 ASIN 会出现好几次
    # （2026-11-04 实测：B0CXSQMQJR 在月度榜里出现 3 次，每次一个日销量）

    by_shop_neg = {}
    for r in negs:
        by_shop_neg.setdefault(r["shop"] or "?", []).append(r)

    def neg_table(rs):
        trs = []
        for r in rs:
            # 销售额 0 却有亏损 = 只有成本没有销售（退货、仓储费、移除费），
            # 跟"卖一单亏一单"是两回事，要标出来
            if r["rev"] <= 0:
                rev_cell = '<span class="tag warn">无销售</span>'
            else:
                rev_cell = "$%s" % format(int(r["rev"]), ",")
            trs.append([r["asin"], r["sku"] or "-", r["name"][:30] or "-", rev_cell,
                        "$%s" % format(int(abs(r["gp"])), ","),
                        ("$%s" % format(int(r["price"]), ",")) if r["price"] else "-"])
        return hr.table(["ASIN", "SKU", "商品", "销售额", "亏损", "采购单价"],
                        trs, align_right={3, 4, 5})

    neg_blocks = []
    # 亏得最多的店排前面
    for shop, rs in sorted(by_shop_neg.items(), key=lambda kv: sum(r["gp"] for r in kv[1])):
        total = sum(r["gp"] for r in rs)
        nosale = len([r for r in rs if r["rev"] <= 0])
        head = ('<p style="margin:14px 0 6px"><b>%s</b>：%d 个亏损，合计亏 <b>$%s</b>'
                % (shop, len(rs), format(int(abs(total)), ",")))
        if nosale:
            head += '（其中 %d 个无销售额，是退货/仓储费不是卖亏）' % nosale
        head += "</p>"
        neg_blocks.append(head + neg_table(rs))

    _worst = (max(by_shop_neg.items(), key=lambda kv: len(kv[1]))[0] if by_shop_neg else "")
    body = (hr.banner(("%d 个 ASIN 在亏钱（%s 占 %d 个），最多亏 $%s" % (
        len(negs), _worst, len(by_shop_neg.get(_worst) or []),
        format(int(abs(negs[0]["gp"])), ","))) if negs
        else ("毛利率 %.1f%%，没有亏损 ASIN" % (mg * 100) if mg is not None else "没有数据"),
        "bad" if (mg is not None and mg < 0) else ("warn" if negs else "good"))
        + c.kpi_cards(cards)
        + hr.section("分店毛利（%s）" % label, hr.table(
            ["店铺", "有成本 ASIN", "销售额", "毛利", "毛利率", "环比", "亏损数", "状态"],
            trs, align_right={1, 2, 3, 4, 5, 6}))
        + (hr.section("亏损明细（全部 %d 个，按店分组）" % len(negs),
                      "".join(neg_blocks)) if negs else
           hr.section("亏损明细", "<p>本期没有亏损的 ASIN。</p>"))
        + hr.section("⚠ 口径（读之前必须知道）", '<ul class="plain">'
            '<li><b>不含头程物流</b>：领星口径扣了采购成本 + FBA 配送费 + 佣金，'
            '但头程运费没录（实测恒为 0），所以毛利率是<b>上限值</b></li>'
            '<li><b>只算有采购成本的 ASIN</b>：本期 %d/%d 个有成本，'
            '没录的不算——把"没录"当"成本 0"会让毛利率虚高</li>'
            '<li><b>阈值</b>：毛利率目标 %.0f%%、低于 %.0f%% 算偏低、&lt;0 亏损'
            '（config/targets.json 的 profit 段）</li>'
            '<li>成本补全后要重跑：覆盖率上去了，毛利率会变（通常是<b>降低</b>）</li>'
            '</ul>' % (res["n"], res["n_all"], tgt * 100, floor * 100)))
    footer = ("口径：领星 query_order_profit_list · USD · 只算有采购成本的 ASIN · "
              "不含头程 · 本期 %s / 上期 %s" % (label, p_label))
    html = hr.render(title="利润复盘（%s）" % ("周" if period == "week" else "月"),
                     subtitle=label, meta="生成 %s" % dt.date.today().isoformat(),
                     banner_html="", body_html=body, footer=footer)
    slug = ("profit_week_%s" % label.replace(" ~ ", "_")) if period == "week" else ("profit_month_%s" % label)
    return hr.save(html, OUT_DIR / ("%s.html" % slug))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--period", default="week", choices=["week", "month"])
    ap.add_argument("--anchor", default="", help="指定日期（周报取那周，月报取那月）")
    ap.add_argument("--format", default="html", choices=["html", "text"])
    args = ap.parse_args()

    rows = load()
    if not rows:
        print("没有 profit_daily（先跑 scripts/fetch_profit.py --days 30）")
        return 2
    anchor = None
    if args.anchor:
        raw = args.anchor.strip()
        try:
            # 月报常传 "2026-10"，要补日；周报传完整日期
            anchor = (dt.date.fromisoformat(raw + "-01") if len(raw) == 7
                      else dt.date.fromisoformat(raw))
        except ValueError:
            print("--anchor 格式不对：用 2026-10 或 2026-11-03")
            return 2
    s, e, ps, pe, label, p_label = period_bounds(args.period, anchor)

    cur = window(rows, s, e)
    prev = window(rows, ps, pe)
    if not cur:
        print("本期（%s）没有数据" % label)
        return 2
    res = agg(cur)
    prev_res = agg(prev)
    by_shop = agg(cur, "shop")
    prev_by_shop = agg(prev, "shop")
    negs = merge_neg(res["neg"])
    prev_negs = merge_neg(prev_res["neg"])

    if args.format == "text":
        mg = res["margin"]
        print("【利润复盘·%s】%s" % ("周" if args.period == "week" else "月", label))
        print("  销售额 $%s / 毛利 $%s / 毛利率 %s" % (
            format(int(res["rev"]), ","), format(int(res["gp"]), ","),
            ("%.1f%%" % (mg * 100)) if mg is not None else "-"))
        print("  亏损 ASIN %d 个（上期 %d 个）" % (len(negs), len(prev_negs)))
        for shop, b in sorted(by_shop.items(), key=lambda kv: -kv[1]["rev"]):
            print("    %-10s $%-9s 毛利 $%-8s %s" % (
                shop, format(int(b["rev"]), ","), format(int(b["gp"]), ","),
                ("%.1f%%" % (b["margin"] * 100)) if b["margin"] is not None else "-"))
    else:
        out = render(res, prev_res, by_shop, prev_by_shop, label, p_label, args.period)
        print("✓ 利润复盘 → %s" % out)
        mg = res["margin"]
        print("  %s：销售额 $%s，毛利率 %s，亏损 %d 个" % (
            label, format(int(res["rev"]), ","),
            ("%.1f%%" % (mg * 100)) if mg is not None else "-", len(negs)))
    return 1 if negs else 0


if __name__ == "__main__":
    sys.exit(main())
