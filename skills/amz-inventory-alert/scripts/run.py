#!/usr/bin/env python3
"""库存与断货预警：按可售天数分档，给补货建议与目标对照。

用法：
  python3 skills/amz-inventory-alert/scripts/run.py
  python3 skills/amz-inventory-alert/scripts/run.py --shop shop_a --format text
  python3 skills/amz-inventory-alert/scripts/run.py --days 7

口径：可售天数 = FBA 可售 ÷ 日均销量（默认近 7 天）。
只算 FBA 可售：在途/本地仓/海外仓不在内，报告逐次披露。
退出码：有"急"或"关注" → 1；数据缺失 → 2；全部正常 → 0。
"""
import argparse
import datetime as dt
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent.parent / "_shared"))
import chartlets as c    # noqa: E402
import html_report as hr  # noqa: E402
import metrics as m      # noqa: E402
import shopdata as sd    # noqa: E402

ROOT = HERE.parent.parent.parent
SHOPS_JSON = ROOT / "config" / "shops.json"
TARGETS_JSON = ROOT / "config" / "targets.json"
OUT_DIR = ROOT / "data" / "reports" / "inventory"

# 分档（可售天数）。阈值真读 config/thresholds.yaml 的 stockout 段：
#   急 = 低于 days_of_supply_critical；关注 = 到 days_of_supply_alert；
#   注意 = 到 low_stock_ratio_vs_28d（28 天候选线）；正常 = 更久。
_DEFAULT_BOUNDS = (10, 21, 28)
_TIER_LABELS = [
    ("急", c.RED, "当天处理：紧急补货 / 转 FBM / 停广告止损"),
    ("关注", c.AMBER, "核对在途与本地仓，走补货流程"),
    ("注意", c.PALETTE[3], "排进本周补货计划"),
    ("正常", c.GREEN, "不动"),
]


def load_tiers():
    """[(档名, 下限, 上限, 颜色, 建议)]；阈值来自 thresholds.yaml 的 stockout 段。"""
    th = m.load_thresholds().get("stockout") or {}
    crit = th.get("days_of_supply_critical")
    alert = th.get("days_of_supply_alert")
    cand = th.get("low_stock_ratio_vs_28d")
    b = tuple(int(x) for x in (crit, alert, cand)) if all(
        isinstance(x, (int, float)) and x > 0 for x in (crit, alert, cand)) else _DEFAULT_BOUNDS
    bounds = [(0, b[0]), (b[0], b[1]), (b[1], b[2]), (b[2], None)]
    return [(lbl[0], lo, hi, lbl[1], lbl[2]) for lbl, (lo, hi) in zip(_TIER_LABELS, bounds)]


TIERS = load_tiers()

# 日均销量低于这个数的 SKU 不报"急"：可售 0 件 + 日均 0.1 件 = 一年卖 36 件，
# 报成"当天必须处理"会把真正的断货兄弟淹掉（2026-11-04 实测 47 个急里大半是这种）
LOW_VELOCITY_DAILY = 0.5


def tier_of(dos, daily=None):
    """可售天数 → (档名, 颜色, 建议)。None（无销量）单独处理。"""
    if dos is None:
        return "零动销", c.GRAY, "近期无销量；确认是否停售品，别当断货急件处理"
    if daily is not None and 0 < daily < LOW_VELOCITY_DAILY and dos < 7:
        return "低频", c.GRAY, "日均不到 %.1f 件，先确认还卖不卖；不值得为它压库存" % LOW_VELOCITY_DAILY
    for name, lo, hi, color, action in TIERS:
        if dos >= lo and (hi is None or dos < hi):
            return name, color, action
    return "正常", c.GREEN, "不动"


def load_targets():
    try:
        return json.loads(TARGETS_JSON.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def shop_level(by_shop, days_window, shops_cfg):
    """店级口径：用 shop_daily 的 fba_available + 近 N 天销量。"""
    rows = []
    latest = sd.latest_by_shop(by_shop)
    for shop, (d, row) in sorted(latest.items()):
        by_date = by_shop.get(shop, {})
        ds = sorted(by_date)
        win = [by_date[x] for x in ds if x <= d][-days_window:]
        units = sum((sd.val(r, "units") or 0) for r in win)
        daily = units / len(win) if win else 0
        avail = sd.val(row, "fba_available")
        dos = (avail / daily) if (avail is not None and daily > 0) else None
        name, color, action = tier_of(dos, daily)
        rows.append({
            "key": shop, "display": shops_cfg.get(shop, {}).get("display", shop),
            "date": d, "avail": avail, "daily": daily, "dos": dos,
            "units_window": units, "tier": name, "color": color, "action": action,
            "inbound": sd.val(row, "available_inventory"),
        })
    return rows


def sku_level(by_shop, days_window, only_shop=None):
    """SKU 级口径：读 inventory_daily + sales_daily。"""
    inv = m.load("inventory_daily")
    if not inv:
        return []
    if only_shop:
        inv = [r for r in inv if r.get("shop") == only_shop]
        if not inv:
            return []
    sales = m.load("sales_daily")
    span = m.table_date_span(sales) or 1
    units = {}
    for r in sales:
        k = r.get("sku") or r.get("asin")
        units[k] = units.get(k, 0.0) + (m.num(r.get("units")) or 0)
    out = []
    for r in inv:
        k = r.get("sku") or r.get("asin")
        avail = m.num(r.get("fba_available"))
        if avail is None or not k:
            continue
        equ_units = (units.get(k, 0.0) * days_window / span) if span else 0
        daily = equ_units / days_window if days_window else 0
        dos = (avail / daily) if daily > 0 else None
        name, color, action = tier_of(dos, daily)
        # display 带产品名和 ASIN：只显示 SKU 号，运营还得去后台查这是哪个产品
        pname = (r.get("product_name") or "").strip()
        asin = (r.get("asin") or "").strip()
        label = k if not pname else "%s（%s）" % (k, pname[:22])
        out.append({"key": k, "display": label, "asin": asin, "sku": k,
                    "product_name": pname,
                    "shop": r.get("shop") or "",
                    "date": m.row_date(r) or "-",
                    "avail": avail, "daily": daily, "dos": dos,
                    "units_window": equ_units, "tier": name, "color": color,
                    "action": action, "inbound": m.num(r.get("fba_inbound"))})
    return out


def build(rows, scope, days_window, targets, as_of):
    counts = {name: sum(1 for r in rows if r["tier"] == name) for name, *_ in TIERS}
    counts["零动销"] = sum(1 for r in rows if r["tier"] == "零动销")
    urgent = counts.get("急", 0)
    watch = counts.get("关注", 0)

    if urgent:
        banner, level = "%d 个对象库存不足 7 天，当天必须处理（%d 个关注、%d 个注意）" % (
            urgent, watch, counts.get("注意", 0)), "bad"
    elif watch:
        banner, level = "%d 个对象库存 7–14 天，本周要补（%d 个注意）" % (
            watch, counts.get("注意", 0)), "warn"
    elif counts.get("注意", 0):
        banner, level = "%d 个对象进入 14–21 天注意区，排进补货计划" % (
            counts["注意"],), "warn"
    elif not rows:
        banner, level = "没有可用的库存数据（见下方数据情况）", "warn"
    else:
        banner, level = "全部 %d 个对象可售天数 ≥21 天，库存健康" % len(rows), "good"

    total_avail = sum((r["avail"] or 0) for r in rows)
    total_daily = sum((r["daily"] or 0) for r in rows)
    weighted_dos = (total_avail / total_daily) if total_daily > 0 else None
    # 加权可售天数会骗人：库存压在少数 SKU 上时，加权平均 158 天，
    # 但同时有 9 个 SKU 已经 0 天（2026-11-04 实测就是这么显示的）。
    # 所以主指标换成"中位数"，加权值只作为附注。
    _dos_list = sorted(r["dos"] for r in rows
                       if r["dos"] is not None and (r.get("daily") or 0) >= LOW_VELOCITY_DAILY)
    median_dos = None
    if _dos_list:
        mid = len(_dos_list) // 2
        median_dos = (_dos_list[mid] if len(_dos_list) % 2 else
                      (_dos_list[mid - 1] + _dos_list[mid]) / 2)

    tgt = (targets.get("inventory") or {})
    tgt_dos = tgt.get("min_days_of_supply")
    cards = [
        {"label": "FBA 可售(件)", "value": c._fmt(total_avail), "note": "仅 FBA 口径"},
        {"label": "可售天数中位数",
         "value": (c._fmt(median_dos, 1) + " 天") if median_dos is not None else "缺数据",
         "note": (("加权平均 %s 天 · 目标 ≥%s 天" % (c._fmt(weighted_dos, 0), tgt_dos))
                  if weighted_dos and tgt_dos
                  else ("加权平均 %s 天" % c._fmt(weighted_dos, 0)) if weighted_dos
                  else "目标未设定")},
        {"label": "急件数", "value": str(urgent), "note": "<7 天"},
        {"label": "关注数", "value": str(watch), "note": "7–14 天"},
    ]

    # 店铺/SKU 分档横条（按可售天数升序，急的在前）
    bars = []
    for r in sorted(rows, key=lambda x: (x["dos"] is None, x["dos"] or 0))[:12]:
        note = ("%s件 / 日均%.1f" % (c._fmt(r["avail"]), r["daily"])) if r["daily"] else "%s件" % c._fmt(r["avail"])
        # 标签用 SKU + 店铺后缀（不同店可能有同一个 SKU，不标店铺会看混）
        _lab = r.get("sku") or r["display"]
        if r.get("shop"):
            _lab = "%s · %s" % (_lab, r["shop"])
        bars.append({"label": _lab, "value": round(r["dos"], 1) if r["dos"] is not None else 0,
                     "color": r["color"], "note": "%s · %s" % (r["tier"], note)})

    # SKU 级要能看到具体是哪个 SKU、哪个 ASIN、哪个店；店级口径没这些字段，退回原表头
    is_sku = scope.startswith("SKU")
    table_rows = []
    for r in sorted(rows, key=lambda x: (x["dos"] is None, x["dos"] or 0)):
        tier_tag = '<span class="tag %s">%s</span>' % (
            {"急": "bad", "关注": "warn", "注意": "warn", "正常": "good"}.get(r["tier"], "warn"),
            r["tier"])
        common = [
            c._fmt(r["avail"]),
            c._fmt(r["daily"], 1) if r["daily"] else "-",
            (c._fmt(r["dos"], 1) + " 天") if r["dos"] is not None else "缺数据",
            c._fmt(r["inbound"]) if r.get("inbound") else "-",
            tier_tag,
            r["action"],
        ]
        if is_sku:
            table_rows.append([
                r.get("sku") or r["display"],
                r.get("asin") or "-",
                r.get("shop") or "-",
                ('<span style="white-space:nowrap">%s</span>' % (r.get("product_name") or "-")[:18]),
            ] + common)
        else:
            table_rows.append([r["display"]] + common)

    notes = [
        "可售天数 = <b>FBA 可售 ÷ 日均销量</b>（近 %d 天）；在途（fba_inbound）、本地仓、海外仓"
        "<b>都不计入</b>——真实可售可能更多，报告不替你猜。" % days_window,
        "断货的伤害是<b>不可逆</b>的：排名掉下去通常要 6–8 周才恢复，比临时改价严重得多。",
        "补货量/交期/起订量<b>必须人工定</b>——本报告只回答「还能卖几天、急不急」。",
        "目标值来自 `config/targets.json`（未设定时显示「目标未设定」，不假装有目标）。",
        "口径：" + scope,
    ]
    body = (hr.banner(banner, level) + c.kpi_cards(cards)
            + hr.section("可售天数（短的在前）",
                         c.hbar_chart(bars, title="可售天数（天）") if bars
                         else "<p>没有可出图的数据。</p>")
            + hr.section("明细" + ("（SKU 级）" if is_sku else ""),
                         (hr.table_filterable(hr.table(
                             ["SKU", "ASIN", "店铺", "商品", "FBA可售", "日均销量",
                              "可售天数", "在途", "档位", "建议"],
                             table_rows, align_right={4, 5, 6, 7}), "invdetail")
                          if is_sku and table_rows else
                          hr.table(["对象", "FBA可售", "日均销量", "可售天数", "在途", "档位", "建议"],
                                   table_rows, align_right={1, 2, 3, 4})
                          if table_rows else "<p>无数据。</p>"))
            + hr.section("⚠ 看这份报告要知道", '<ul class="plain">%s</ul>'
                         % "".join("<li>%s</li>" % n for n in notes)))
    body += hr.methodology([
        ("可售天数", "FBA 可售 ÷ 日均销量；店级加权可售天数 = Σ 可售 ÷ Σ 日均（非简单平均）"),
        ("分档阈值", "急 &lt;7 天（当天处理：紧急补货/转 FBM/停广告止损）；关注 7–14 天（核对在途走补货）；注意 14–21 天（进本周计划）；正常 ≥21 天"),
        ("零动销保护", "日均销量低于下限的 SKU 不报「急」：可售 0 + 日均 0.1 件这类停售/近停售品，按零动销观察，避免淹没真断货"),
        ("金额口径", "涉及金额均为 USD（美金），系统不做币种换算"),
        ("退出码", "有急/关注 → 1（成功但有告警，仍归档）；数据缺失 → 2（不归档）；全部正常 → 0"),
    ])
    footer = ("口径：%s · 数据截至 %s · 阈值 config/thresholds.yaml 的 stockout 段 · "
              "目标 config/targets.json" % (scope, as_of))
    return hr.render(title="库存与断货预警", subtitle=scope, meta="生成 %s" % dt.date.today().isoformat(),
                     banner_html="", body_html=body, footer=footer), urgent + watch


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--shop", default="", help="只看看某店铺组")
    ap.add_argument("--days", type=int, default=7, help="日均销量用近 N 天（默认 7）")
    ap.add_argument("--format", default="html", choices=["html", "text"])
    args = ap.parse_args()

    shops_cfg = json.loads(SHOPS_JSON.read_text(encoding="utf-8"))["shops"]
    by_shop = sd.load_by_shop()
    if args.shop:
        by_shop = {k: v for k, v in by_shop.items() if k == args.shop}
        if not by_shop:
            print("未知店铺组 %r（可选：%s）" % (args.shop, ", ".join(shops_cfg)))
            return 2

    # 优先 SKU 级：断货是一个个 SKU 断的，店级汇总会把"某个 SKU 已经 0 了"
    # 埋在"全店还能卖 30 天"里。店级只在没有 inventory_daily 时兜底。
    rows = sku_level(by_shop, args.days, only_shop=args.shop or None)
    scope = "SKU 级口径（inventory_daily）"
    if not rows:
        rows = shop_level(by_shop, args.days, shops_cfg) if by_shop else []
        scope = "店铺组（店级口径）"

    if not rows:
        print("没有库存数据：先跑 scripts/fetch_lingxing.py 拉店铺数据，"
              "或导 inventory_daily（SKU 级）。退出码 2。")
        return 2

    as_of = max((r["date"] for r in rows), default="-")
    html, need_action = build(rows, scope, args.days, load_targets(), as_of)

    if args.format == "text":
        urgent = [r for r in rows if r["tier"] == "急"]
        watch = [r for r in rows if r["tier"] == "关注"]
        if not urgent and not watch:
            print("【库存】%d 个对象可售天数均 ≥14 天，无需处理。" % len(rows))
        else:
            print("【库存】急 %d / 关注 %d：" % (len(urgent), len(watch)))
            for r in (urgent + watch)[:6]:
                print("  [%s] %s 可售 %s 天（%s 件 / 日均 %.1f）— %s" % (
                    r["tier"], r["display"],
                    c._fmt(r["dos"], 1) if r["dos"] is not None else "缺",
                    c._fmt(r["avail"]), r["daily"], r["action"]))
        return 1 if need_action else 0

    out = hr.save(html, OUT_DIR / ("%s_inventory.html" % as_of))
    print("✓ 库存预警 → %s" % out)
    print("  %s：急 %d / 关注 %d / 注意 %d / 正常 %d" % (
        scope,
        sum(1 for r in rows if r["tier"] == "急"),
        sum(1 for r in rows if r["tier"] == "关注"),
        sum(1 for r in rows if r["tier"] == "注意"),
        sum(1 for r in rows if r["tier"] == "正常")))
    return 1 if need_action else 0


if __name__ == "__main__":
    sys.exit(main())
