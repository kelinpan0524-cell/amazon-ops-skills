#!/usr/bin/env python3
"""广告异常监控：读 ads_daily（campaign 级），找出今天真正在烧钱的，只出建议不改竞价。

用法：
  python3 skills/amz-ads-diagnose/scripts/run.py
  python3 skills/amz-ads-diagnose/scripts/run.py --format text
  python3 skills/amz-ads-diagnose/scripts/run.py --days 3 --shop shop_a

数据：data/normalized/ads_daily.csv（scripts/fetch_ads.py 拉，按天增量）。
退出码：有 critical（烧钱/严重超线）→ 1；否则 0；没数据 → 2。

为什么用「花费 × 订单 × ACOS」三件套而不是只看 ACOS：
ACOS 在订单少的时候极不稳定（1 单变成 2 单 ACOS 就砍半），
必须先看"有没有烧钱"（花了多少、有没有单），再看效率。
"""
import argparse
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent.parent / "_shared"))
import benchmarks as bm   # noqa: E402
import chartlets as c     # noqa: E402
import html_report as hr  # noqa: E402
import metrics as m       # noqa: E402

ROOT = HERE.parent.parent.parent
OUT_DIR = ROOT / "data" / "reports" / "ads"
T = m.load_thresholds().get("ads") or {}
TGT = bm.load_targets().get("company") or {}

# 判断门槛（配置优先，缺省用下面这些）
MIN_CLICKS = int(T.get("min_clicks_for_judgement") or 8)
NO_ORDER_SPEND = float(T.get("high_spend_no_order") or 15.0)
ACOS_CEILING = float(TGT.get("acos_ceiling") or 0.18)      # 18% 以上就算高（老板口径）
ACOS_CRITICAL = float(TGT.get("acos_critical") or 0.25)    # 25% 以上要动手
# ACOS 只在花费够大时才判：花 $0.3 出 1 单 ACOS 能到 300%，那是分母太小不是问题
ACOS_MIN_SPEND = float(T.get("acos_min_spend") or 10.0)


def load_rows(days=None, shop=None, table=None):
    """读广告数据。优先 ASIN 级（ads_asin_daily），没有就退回 campaign 级（ads_daily）。

    为什么要 ASIN 级：campaign 级只能说"这条活动今天烧了 200 块"，
    回答不了"是哪个产品在烧"——改价/停投都要落到具体 ASIN 上。
    """
    table = table or ("ads_asin_daily" if m.load("ads_asin_daily") else "ads_daily")
    rows = m.load(table)
    out = []
    for r in rows:
        d = m.row_date(r)
        if not d:
            continue
        if shop and r.get("shop") != shop:
            continue
        out.append((d, r))
    if not out:
        return {}, {}
    ds = sorted({d for d, _ in out})
    keep = set(ds[-days:]) if days else set(ds)
    by_date = {}
    for d, r in out:
        if d in keep:
            by_date.setdefault(d, []).append(r)
    return by_date, {d: by_date[d] for d in sorted(by_date)}


def judge(days_map):
    """扫异常。返回 (alerts, summary)。

    一个 campaign 只在「最新一天」判一次，避免同一问题连报多天；
    环比用倒数第二天做基准。
    """
    if not days_map:
        return [], {}
    ds = sorted(days_map)
    cur_d = ds[-1]
    prev_d = ds[-2] if len(ds) >= 2 else None
    def _obj(r):
        """判断对象：有 ASIN 用 ASIN（更细），否则用 campaign。"""
        return (r.get("shop"), r.get("asin") or r.get("campaign_id"))

    prev_by = {}
    if prev_d:
        for r in days_map[prev_d]:
            prev_by[_obj(r)] = r

    alerts, seen = [], set()

    def add(level, shop, name, msg, action, cid=""):
        k = (shop, cid or name, msg[:20])
        if k in seen:
            return
        seen.add(k)
        alerts.append({"level": level, "shop": shop, "campaign": name,
                       "asin": asin, "sku": sku, "campaign_name": camp,
                       "msg": msg, "action": action})

    for r in days_map[cur_d]:
        shop = r.get("shop") or ""
        asin = str(r.get("asin") or "")
        sku = str(r.get("sku") or "")
        camp = str(r.get("campaign") or r.get("campaign_name") or "")
        # 显示名：有 ASIN 就 SKU(ASIN)，否则 campaign 名——运营要能直接拿去后台搜
        name = ("%s（%s）" % (sku, asin)) if asin and sku else (asin or camp[:40] or "(未命名)")
        cid = asin or str(r.get("campaign_id") or "")
        spend = m.num(r.get("spend") or r.get("spends")) or 0
        sales = m.num(r.get("sales")) or 0
        orders = m.num(r.get("orders")) or 0
        clicks = m.num(r.get("clicks")) or 0
        acos = m.num(r.get("acos"))

        # 1) 烧钱：花了钱没出单
        if spend >= NO_ORDER_SPEND and orders == 0 and clicks >= MIN_CLICKS:
            add("critical", shop, name,
                "花了 $%s / %d 次点击，%d 单" % (format(int(spend), ","), int(clicks), int(orders)),
                "先看是不是词跑偏了（拉搜索词报告）；不改竞价，先加否词或停掉最贵的那几个词")
            continue

        # 2) ACOS 超线（有单才看 ACOS，没单上面那条已经报了）
        if orders >= 1 and acos and spend >= ACOS_MIN_SPEND:
            if acos >= ACOS_CRITICAL:
                add("critical", shop, name,
                    "ACOS %.0f%%（红线 %.0f%%），花 $%s 出 %d 单" % (
                        acos * 100, ACOS_CRITICAL * 100, format(int(spend), ","), int(orders)),
                    "按目标 ACOS 反推：竞价下调约 %.0f%%；别一刀切关掉，先降 15-20%% 观察 3 天"
                    % ((1 - ACOS_CEILING / acos) * 100))
            elif acos >= ACOS_CEILING:
                add("high", shop, name,
                    "ACOS %.0f%% 超过 %.0f%% 的线，花 $%s 出 %d 单" % (
                        acos * 100, ACOS_CEILING * 100, format(int(spend), ","), int(orders)),
                    "看是不是客单价低的词占了预算；先小幅降价（10%%）而不是关掉")

        # 3) 花费骤增（昨天没花这么多）
        p = prev_by.get(_obj(r))
        if p:
            ps = m.num(p.get("spend") or p.get("spends")) or 0
            if ps >= 1 and spend >= max(ps * 2, 30):
                add("high", shop, name,
                    "花费 $%s → $%s（+%.0f%%），单量 %d → %d" % (
                        format(int(ps), ","), format(int(spend), ","),
                        (spend - ps) / ps * 100,
                        int(m.num(p.get("orders")) or 0), int(orders)),
                    "预算被放大或竞价被系统抬高：先确认是不是自己改的；不是就查有没有被抢流量")

    order = {"critical": 0, "high": 1}
    alerts.sort(key=lambda a: (order.get(a["level"], 9), a["shop"]))
    total_spend = sum(m.num(r.get("spend") or r.get("spends")) or 0 for r in days_map[cur_d])
    total_sales = sum(m.num(r.get("sales")) or 0 for r in days_map[cur_d])
    _is_asin = any(r.get("asin") for r in days_map[cur_d])
    # 花费 Top：即使没有异常，老板/运营也想看到"钱到底花在哪个产品上"
    top = []
    for r in sorted(days_map[cur_d],
                    key=lambda x: -(m.num(x.get("spend") or x.get("spends")) or 0))[:15]:
        sp = m.num(r.get("spend") or r.get("spends")) or 0
        if sp <= 0:
            continue
        top.append({
            "asin": r.get("asin") or "", "sku": r.get("sku") or "",
            "campaign": str(r.get("campaign") or r.get("campaign_name") or "")[:34],
            "shop": r.get("shop") or "", "spend": sp,
            "sales": m.num(r.get("sales")) or 0,
            "orders": m.num(r.get("orders")) or 0,
            "acos": m.num(r.get("acos")),
        })
    return alerts, {"date": cur_d, "campaigns": len(days_map[cur_d]),
                    "scope": "ASIN 级" if _is_asin else "Campaign 级", "top": top,
                    "spend": total_spend, "sales": total_sales,
                    "tacos": (total_spend / total_sales) if total_sales else None}


def render_text(alerts, s):
    if not s:
        return "【广告监控】没有 ads_daily 数据（先跑 scripts/fetch_ads.py）"
    head = "【广告异常】%s：%d 条 %s，花 $%s / 回 $%s" % (
        s["date"], s["campaigns"], s.get("scope", "campaign"),
        format(int(s["spend"]), ","), format(int(s["sales"]), ","))
    if not alerts:
        return head + "\n没有烧钱或超线的 campaign。"
    lines = [head, "要处理 %d 条（critical %d / high %d）：" % (
        len(alerts), sum(1 for a in alerts if a["level"] == "critical"),
        sum(1 for a in alerts if a["level"] == "high"))]
    for a in alerts[:6]:
        lines.append("[%s] %s %s — %s" % (a["level"], a["shop"], a["campaign"], a["msg"]))
    if len(alerts) > 6:
        lines.append("…等 %d 条，详见报告" % len(alerts))
    return "\n".join(lines)


def render_html(alerts, s):
    n_crit = sum(1 for a in alerts if a["level"] == "critical")
    n_high = sum(1 for a in alerts if a["level"] == "high")
    cards = [
        {"label": "花费", "value": "$%s" % format(int(s["spend"]), ",")},
        {"label": "广告销售额", "value": "$%s" % format(int(s["sales"]), ",")},
        {"label": "TACOS", "value": c.pct_int(s["tacos"]) if s["tacos"] is not None else "缺数据",
         "note": "广告花费 ÷ 广告销售额"},
        {"label": "要处理", "value": "%d 条" % len(alerts),
         "note": "critical %d / high %d" % (n_crit, n_high)},
    ]
    if alerts:
        rows = [[
            a["shop"], a.get("asin") or "-", a.get("sku") or "-",
            (a.get("campaign_name") or "")[:26] or "-",
            '<span class="tag %s">%s</span>' % ("bad" if a["level"] == "critical" else "warn", a["level"]),
            a["msg"], a["action"]] for a in alerts]
        inner = hr.table(["店铺", "ASIN", "SKU", "Campaign", "级别", "现象", "先做什么"], rows)
    else:
        inner = "<p>今天没有烧钱或 ACOS 超线的对象。</p>"
    note = ('<p style="font-size:11.5px;color:#6b7280;margin-top:8px;line-height:1.75">'
            '判断顺序：先看「花了钱没出单」（>=$%s 且点击 >=%d），再看有单的 ACOS。'
            'ACOS 在订单少时极不稳定，所以不拿绝对值单挑。'
            '阈值：ACOS %.0f%% 算高、%.0f%% 要动手（可在 config/targets.json 改）。'
            '成本未校准，ACOS 不能当盈亏结论。</p>' % (
                format(int(NO_ORDER_SPEND), ","), MIN_CLICKS,
                ACOS_CEILING * 100, ACOS_CRITICAL * 100))
    body = (hr.banner(("有 %d 条 critical：今天在烧钱" % n_crit) if n_crit
                      else ("有 %d 条 high 值得看" % n_high if n_high else "广告今天没有异常"),
                      "bad" if n_crit else ("warn" if n_high else "good"))
            + c.kpi_cards(cards)
            + hr.section("异常清单（按级别排序）", inner + note)
            + (hr.section("花费 Top 15（钱花在哪了）", hr.table(
                ["店铺", "ASIN", "SKU", "Campaign", "花费", "广告销售额",
                 "单", "ACOS"],
                [[x["shop"], x["asin"] or "-", x["sku"] or "-", x["campaign"] or "-",
                  "$%s" % format(int(x["spend"]), ","),
                  "$%s" % format(int(x["sales"]), ","),
                  str(int(x["orders"])),
                  ("%.0f%%" % (x["acos"] * 100)) if x["acos"] else "-"]
                 for x in s.get("top") or []],
                align_right={4, 5, 6, 7})) if s.get("top") else ""))
    body += hr.methodology([
        ("金额口径", "全部 USD（美金）；广告报表为领星广告接口返回，系统不做币种换算"),
        ("高花费 0 单（critical）", "单活动/ASIN 当日花费 ≥ $%s 且订单 = 0 且点击 ≥ 最小点击数（阈值 config/alert_rules.json: ads.high_spend_no_order）" % NO_ORDER_SPEND),
        ("ACOS 超线", "ACOS = 花费 ÷ 广告销售额；有订单且花费达下限后，ACOS &gt; %.0f%% 判 critical 需动手（targets.json: acos_critical）" % (ACOS_CRITICAL * 100)),
        ("花费异常", "单日花费超过既有日均 2 倍且 ≥$30 时提示核查（防预算失控/异常扣费）"),
        ("SKU 级", "ads_asin_daily 提供商品/ASIN 级明细；广告 0 单清单在每日简报与群卡片同步列出"),
        ("退出码", "有 critical → 1（成功但有告警，仍归档）；无数据 → 2；其余 0"),
    ])
    footer = (("口径：%s（领星 %s）· USD · 下单口径；" % (
        s.get("scope", "campaign 级"),
        "ad_campaign_product_report，商品粒度" if s.get("scope") == "ASIN 级"
        else "ad_campaign_report，活动粒度"))
              + "销售为广告销售额（不是店铺总销售额）；成本未校准，ACOS 只看效率不当盈亏。"
              "数据截至 %s，共 %d 条 %s。" % (s["date"], s["campaigns"], s.get("scope", "campaign"))
              + "粒度说明：本地 ads_asin_daily 为 ASIN×广告组×日（含 0 花费），多维表格仅推送有花费行并按 日期+店铺+ASIN+Campaign 去重（2026-11-04 核查无重复）。")
    html = hr.render(title="广告异常监控",
                     subtitle="%s · 只出建议不改竞价" % s.get("scope", "campaign 级"),
                     meta="数据截至 %s" % s["date"], banner_html="",
                     body_html=body, footer=footer)
    return hr.save(html, OUT_DIR / ("%s_ads.html" % s["date"]))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=3, help="用最近 N 天（默认 3，取最后一天判）")
    ap.add_argument("--shop", default="", help="只看某店铺组")
    ap.add_argument("--format", default="html", choices=["html", "text"])
    args = ap.parse_args()

    if not m.load("ads_asin_daily") and not m.load("ads_daily"):
        print("没有广告数据（先跑 scripts/fetch_ads.py --days 7）")
        return 2
    _, days_map = load_rows(args.days, args.shop or None)
    alerts, summary = judge(days_map)
    if not summary:
        print("窗口内没有可用数据")
        return 2

    if args.format == "text":
        print(render_text(alerts, summary))
    else:
        out = render_html(alerts, summary)
        print("✓ 广告异常监控 → %s" % out)
        print(render_text(alerts, summary))
    return 1 if any(a["level"] == "critical" for a in alerts) else 0


if __name__ == "__main__":
    sys.exit(main())
