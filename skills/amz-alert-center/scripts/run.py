#!/usr/bin/env python3
"""经营预警中心：按 config/alert_rules.json 的规则扫描经营数据，分级输出预警清单。

十类规则覆盖：断货、断货风险、销售骤降、周趋势、有花费无单、ACOS 两档、
退货率两档、数据新鲜度、月度目标落后。规则与阈值都在 config/alert_rules.json，
不带任何外部接口依赖。

用法：
  python3 skills/amz-alert-center/scripts/run.py
  python3 skills/amz-alert-center/scripts/run.py --shop shop_a --min-level high
  python3 skills/amz-alert-center/scripts/run.py --format text

退出码：存在 critical/high 预警 → 1（便于定时任务据此决定是否叫人）；否则 0。
口径：shop_daily（USD/下单）；成本未校准，ACOS 类预警只说效率不说盈亏。
"""
import argparse
import datetime as dt
import json
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent.parent / "_shared"))
import chartlets as c    # noqa: E402
import html_report as hr  # noqa: E402
import metrics as m
import benchmarks as bm      # noqa: E402
import shopdata as sd    # noqa: E402  （共享读取层）

ROOT = HERE.parent.parent.parent
SHOPS_JSON = ROOT / "config" / "shops.json"
RULES_JSON = ROOT / "config" / "alert_rules.json"
OUT_DIR = ROOT / "data" / "reports" / "alerts"
LEVEL_ORDER = {"critical": 0, "high": 1, "medium": 2, "low": 3}
LEVEL_TAG = {"critical": "bad", "high": "bad", "medium": "warn", "low": "good"}
LEVEL_CN = {"critical": "紧急", "high": "高", "medium": "中", "low": "低"}

def load_rules():
    return json.loads(RULES_JSON.read_text(encoding="utf-8")).get("rules", [])
















def load_fetch_status():
    path = ROOT / "data" / "logs" / "fetch_status.json"
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data.get("sources") if isinstance(data.get("sources"), dict) else {}
    except (OSError, json.JSONDecodeError) as exc:
        print("! fetch_status 不可读，将按状态未知处理：%s" % exc, file=sys.stderr)
        return {}


def build_index():
    """{shop: {date: row}} 与每店最新日期。"""
    idx, latest = {}, {}
    for r in m.load("shop_daily"):
        d, shop = m.row_date(r), r.get("shop")
        if d and shop:
            idx.setdefault(shop, {})[d] = r
            if shop not in latest or d > latest[shop]:
                latest[shop] = d
    return idx, latest


# 数值读取统一走共享层（缺数返回 None，不冒充 0）
num = sd.val


def scan(idx, latest, shops_cfg, rules, only_shop=None, min_level="low"):
    """跑本机规则，返回 [alert...]。每条 alert 含 level/rule/shop/msg/action。"""
    alerts = []
    enabled = {r["id"]: r for r in rules if r.get("enabled")}
    today = dt.date.today()
    fetch_sources = load_fetch_status()

    def add(rule_id, shop, msg, level=None):
        rule = enabled.get(rule_id)
        if not rule:
            return
        lv = level or rule.get("level", "medium")
        if LEVEL_ORDER[lv] > LEVEL_ORDER.get(min_level, 3):
            return
        # 旧多维表格没有毛利两档选项；留空表示不写旧表，避免整批写入被拒。
        bitable_rule = "" if rule_id.startswith("gross-margin-") else rule["name"]
        alerts.append({"level": lv, "rule": rule["name"], "shop": shop,
                       "msg": msg, "action": rule.get("action", ""),
                       "why": rule.get("why", ""), "source": "local",
                       "bitable_rule": bitable_rule})

    for shop, by_date in idx.items():
        if only_shop and shop != only_shop:
            continue
        disp = shops_cfg.get(shop, {}).get("display", shop)
        dates = sorted(by_date)
        if not dates:
            continue
        full = [d for d in dates if d != today.isoformat()] or dates
        cur_d = full[-1]
        cur = by_date[cur_d]
        prev = by_date[full[-2]] if len(full) >= 2 else None

        # ---- 数据新鲜度：日期与真实拉取状态联合裁决，避免把正常 T+1 误报成断供 ----
        lag_days = (today - dt.date.fromisoformat(cur_d)).days
        freshness = m.data_freshness(lag_days, fetch_sources.get("lingxing"), today=today)
        state = freshness["state"]
        if state != "normal":
            if state == "fetch_failed":
                rule_id = "data-fetch-failed"
            elif freshness["level"] == "high":
                rule_id = "data-stale"
            else:
                rule_id = "data-delay"
            add(rule_id, shop, "%s 最新数据 %s：%s" % (disp, cur_d, freshness["message"]),
                level=freshness["level"])

        # ---- 月度目标落后（按进度而不是绝对达成率）----
        rule = enabled.get("target-behind")
        if rule:
            mon = cur_d[:7]
            mtd = sum((m.num(by_date[d].get("revenue")) or 0)
                      for d in dates if d[:7] == mon)
            prog = bm.month_progress_ratio(shop, mtd, cur_d)
            if prog and prog["tprog"] >= rule.get("min_progress", 0.4):
                if prog["ratio"] < rule.get("critical_ratio", 0.6):
                    add("target-behind", shop,
                        "%s 当月已卖 $%s，目标 $%s（达成 %.0f%%，时间已过 %.0f%%）——"
                        "严重落后，剩 %d 天" % (
                            disp, format(int(prog["mtd"]), ","),
                            format(int(prog["target_usd"]), ","),
                            prog["pct"] * 100, prog["tprog"] * 100, prog["days_left"]),
                        level="critical")
                elif prog["ratio"] < rule.get("threshold", 0.8):
                    add("target-behind", shop,
                        "%s 当月已卖 $%s，目标 $%s（达成 %.0f%%，时间已过 %.0f%%）——"
                        "落后进度，剩 %d 天" % (
                            disp, format(int(prog["mtd"]), ","),
                            format(int(prog["target_usd"]), ","),
                            prog["pct"] * 100, prog["tprog"] * 100, prog["days_left"]))

        # ---- 销售骤降 ----
        rev, prev_rev = num(cur, "revenue"), num(prev, "revenue")
        rule = enabled.get("sales-drop")
        if rule and rev is not None and prev_rev:
            drop = (prev_rev - rev) / prev_rev
            if drop >= rule["threshold"]:
                add("sales-drop", shop, "%s %s 销售额 %s，较 %s 跌 %.0f%%"
                    % (disp, cur_d, c.money_usd(rev), full[-2], drop * 100))

        # ---- ACOS / 花费无单 ----
        acos_v, spend, orders = num(cur, "acos"), num(cur, "spend"), num(cur, "orders")
        # 两档：18% 提醒、25% 严重（只报最高那档，避免同一件事报两条）
        crit = enabled.get("acos-critical")
        warn = enabled.get("acos-high")
        if acos_v is not None:
            if crit and acos_v > crit["threshold"]:
                add("acos-critical", shop, "%s %s ACOS %.0f%%（严重，花费 $%s）"
                    % (disp, cur_d, acos_v * 100, format(round(spend or 0), ",")))
            elif warn and acos_v > warn["threshold"]:
                add("acos-high", shop, "%s %s ACOS %.0f%%（花费 $%s）"
                    % (disp, cur_d, acos_v * 100, format(round(spend or 0), ",")))
        rule = enabled.get("spend-no-order")
        if rule and spend is not None and spend > rule["threshold"] and (orders or 0) <= 0:
            add("spend-no-order", shop, "%s %s 广告花费 $%s 但 0 单"
                % (disp, cur_d, format(round(spend), ",")))

        # ---- 库存（期末快照）----
        fba = num(cur, "fba_available")
        store_policy = m.inventory_policy("store")
        recent = [by_date[d] for d in full[-store_policy["window"]:]]
        units_7d = sum((num(r, "units") or 0) for r in recent)
        daily_u = units_7d / max(len(recent), 1)
        rule = enabled.get("stock-out")
        if rule and fba is not None and fba <= 0 and units_7d > 0:
            add("stock-out", shop, "%s FBA 可售为 0，但近 %d 天卖了 %.0f 件（正在掉排名）"
                % (disp, len(recent), units_7d))
        rule = enabled.get("stock-risk")
        if rule and fba and daily_u > 0:
            dos = fba / daily_u
            if dos < store_policy["risk"]:
                add("stock-risk", shop, "%s FBA 可售约 %.0f 天（%s 件 ÷ 日均 %.1f 件）"
                    % (disp, dos, format(round(fba), ","), daily_u))

        # ---- 退货率 ----
        # 退货率两档：日线 8% 预警；月线 9.1% 是亚马逊官方收费线（Automotive & Powersports）
        rr = num(cur, "return_rate")
        rule = enabled.get("return-rate-watch")
        if rule and rr is not None and rr > rule["threshold"]:
            add("return-rate-watch", shop, "%s %s 退货率 %.1f%%（接近收费线 9.1%%）"
                % (disp, cur_d, rr * 100))
        # 月退货率：用最近 30 天的退货件数/发货件数近似（字段只有日级时按日出）
        m_rule = enabled.get("return-rate-critical")
        if m_rule:
            recent30 = [by_date[d] for d in full[-30:]]
            ret_units = sum((num(r, "refund_units") or 0) for r in recent30)
            shipped = sum((num(r, "units") or 0) for r in recent30)
            if shipped >= 25:  # 亚马逊对月发货 <25 件的豁免
                mrr = ret_units / shipped
                if mrr > m_rule["threshold"]:
                    add("return-rate-critical", shop,
                        "%s 近 30 天退货率 %.1f%%（超亚马逊汽配收费线 9.1%%，发货 %d 件）"
                        % (disp, mrr * 100, shipped))

        # ---- 周趋势 ----
        rule = enabled.get("sales-trend-down")
        if rule and len(full) >= 14:
            last7 = sum((num(by_date[d], "revenue") or 0) for d in full[-7:])
            prev7 = sum((num(by_date[d], "revenue") or 0) for d in full[-14:-7])
            if prev7 and (prev7 - last7) / prev7 >= rule["threshold"]:
                add("sales-trend-down", shop, "%s 近 7 天 $%s，较前 7 天跌 %.0f%%"
                    % (disp, format(round(last7), ","), (prev7 - last7) / prev7 * 100))

    # ---- 毛利率过低 / 毛利为负（数据源 profit_daily，独立于 shop_daily）----
    # 只统计录了采购成本的 ASIN（has_cost=1）：把"没录"当"成本 0"会把毛利率算虚高
    prof = m.load("profit_daily")
    if prof and (enabled.get("gross-margin-low") or enabled.get("gross-margin-negative")):
        with_cost = [r for r in prof if (m.num(r.get("has_cost")) or 0) > 0]
        ds = sorted({m.row_date(r) for r in with_cost if m.row_date(r)})
        if ds:
            cur_d = ds[-1]
            cur = [r for r in with_cost if m.row_date(r) == cur_d]
            # 按店聚合
            by_shop_p = {}
            for r in cur:
                b = by_shop_p.setdefault(r.get("shop") or "?", {"rev": 0.0, "gp": 0.0, "neg": []})
                rev = m.num(r.get("revenue")) or 0
                gp = m.num(r.get("gross_profit")) or 0
                b["rev"] += rev
                b["gp"] += gp
                if gp < 0:
                    b["neg"].append((gp, r.get("asin") or "", r.get("sku") or "", rev))
            rule_low = enabled.get("gross-margin-low")
            rule_neg = enabled.get("gross-margin-negative")
            for shop, b in by_shop_p.items():
                if only_shop and shop != only_shop:
                    continue
                disp_s = shops_cfg.get(shop, {}).get("display", shop)
                margin = (b["gp"] / b["rev"]) if b["rev"] else None
                if margin is None:
                    continue
                if rule_neg and margin < (rule_neg.get("threshold") or 0):
                    add("gross-margin-negative", shop,
                        "%s 当天毛利率 %.1f%%（销售额 $%s / 毛利 $%s）—— 整店在亏"
                        % (disp_s, margin * 100, format(int(b["rev"]), ","),
                           format(int(b["gp"]), ",")), level="critical")
                elif rule_low and margin < (rule_low.get("threshold") or 0.15):
                    add("gross-margin-low", shop,
                        "%s 当天毛利率 %.1f%%（低于 %.0f%% 的线；销售额 $%s / 毛利 $%s）"
                        % (disp_s, margin * 100, (rule_low.get("threshold") or 0.15) * 100,
                           format(int(b["rev"]), ","), format(int(b["gp"]), ",")))
                # 单 ASIN 亏损：只报亏损额最大的 3 个，避免刷屏（实测 12% 的 ASIN 在亏）
                if rule_neg and b["neg"]:
                    top = sorted(b["neg"])[:3]
                    for gp, asin, sku, rev in top:
                        add("gross-margin-negative", shop,
                            "%s %s 单 ASIN 毛利 -$%s（销售额 $%s）—— 卖一单亏一单"
                            % (disp_s, (sku or asin), format(int(abs(gp)), ","),
                               format(int(rev), ",")), level="critical")

    alerts.sort(key=lambda a: (LEVEL_ORDER[a["level"]], a["shop"]))
    # ---- 跟卖预警（读 amz-hijack-watch 最新快照；sellers>1 = 有其他卖家）----
    hijack_rule = enabled.get("hijack-seller")
    if hijack_rule:
        raw_dir = ROOT / "data" / "raw" / "hijack"
        snaps = sorted(raw_dir.glob("*.json")) if raw_dir.exists() else []
        if snaps:
            try:
                snap = json.loads(snaps[-1].read_text(encoding="utf-8"))
                for asin, it in (snap.get("items") or {}).items():
                    sellers = (it or {}).get("sellers")
                    if sellers and sellers > 1:
                        add("hijack-seller", "-",
                            "%s 出现跟卖（卖家数 %s，快照 %s）" % (asin, sellers, snap.get("date")))
            except Exception:
                pass
    return alerts


def render_text(alerts):
    if not alerts:
        text = "【经营预警】全部正常，无需处理。"
    else:
        lines = ["【经营预警】%d 条待处理（%s）" % (
            len(alerts), "、".join("%s %d" % (LEVEL_CN[l], sum(1 for a in alerts if a["level"] == l))
                                  for l in ("critical", "high", "medium") if any(a["level"] == l for a in alerts)))]
        for a in alerts[:8]:
            lines.append("[%s] %s — %s" % (LEVEL_CN[a["level"]], a["msg"], a["action"]))
        if len(alerts) > 8:
            lines.append("…等 %d 条，详见报告" % len(alerts))
        text = "\n".join(lines)
    return text


def render_html(alerts, as_of):
    counts = {l: sum(1 for a in alerts if a["level"] == l) for l in LEVEL_ORDER}
    if not alerts:
        banner_txt, level = "全部正常：预警都没触发（扫描至 %s）" % as_of, "good"
    elif counts["critical"]:
        banner_txt, level = "紧急 %d 条 / 高 %d 条，今天必须处理" % (counts["critical"], counts["high"]), "bad"
    elif counts["high"]:
        banner_txt, level = "高优先 %d 条，建议今天处理" % counts["high"], "bad"
    else:
        banner_txt, level = "中优先 %d 条，可并入日报处理" % counts["medium"], "warn"

    rows = [[
        '<span class="tag %s">%s</span>' % (LEVEL_TAG[a["level"]], LEVEL_CN[a["level"]]),
        a["rule"], a["shop"], a["msg"], a["action"],
    ] for a in alerts]
    body = hr.banner(banner_txt, level) + (
        hr.section("预警清单", hr.table(["级别", "类型", "店铺", "现象", "该怎么办"], rows))
        if alerts else hr.section("预警清单", "<p>所有规则均未触发。</p>"))
    source_note = (
        "<li>全部规则来自本机 <code>config/alert_rules.json</code>（阈值与开关都在那里改）。</li>"
        "<li>数据断供/月度目标/毛利/跟卖同样走本机规则，不依赖任何外部接口。</li>"
    )
    body += hr.section("⚠ 读这份清单要知道", '<ul class="plain">'
                       "%s"
                       "<li>ACOS 预警只说广告效率高低；<b>成本未校准，不能当盈亏结论</b>。</li>"
                       "<li>断货预警只算 FBA 可售，不含在途/本地仓/海外仓。</li>"
                       "<li>预警只叫人和给建议，<b>改价/停广告/下单永远人工做</b>。</li></ul>" % source_note)
    body += hr.methodology([
        ("金额口径", "全部 USD（美金），领星折算返回，不做币种换算"),
        ("目标掉队 target-behind", "月度达成率 ÷ 时间进度 &lt;0.8 预警、&lt;0.6 严重；时间进度 = 当月已过天数 ÷ 当月天数；月时间进度 ≥40% 才启用该规则，避免月初误报"),
        ("销量下滑 sales-drop", "销售额环比 =（前日 − 当日）÷ 前日，超过配置跌幅阈值触发"),
        ("库存类", "可售天数 = FBA 可售 ÷ 近 28 天等效日均销量；急 &lt;10 天、关注 10–21 天"),
        ("广告类", "高花费 0 单 / ACOS 超红线等，阈值取 config/alert_rules.json（ads 段）与 targets.json"),
        ("开关与阈值", "各规则可在 config/alert_rules.json 按 enabled 开关；阈值未校准项属经验占位，校准方法见 docs/THRESHOLD-CALIBRATION.md"),
    ])
    footer = ("口径：shop_daily（领星 total_sum）· USD · 下单口径；"
              "全部规则来自本机配置；扫描至 %s。" % as_of)
    return hr.render(title="经营预警", subtitle="本机规则扫描",
                     meta="扫描日 %s" % dt.date.today().isoformat(),
                     banner_html="", body_html=body, footer=footer)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--shop", default="", help="只看某店铺组")
    ap.add_argument("--min-level", default="low", choices=list(LEVEL_ORDER),
                    help="最低输出级别（low 全出）")
    ap.add_argument("--format", default="html", choices=["html", "text"])
    args = ap.parse_args()

    shops_cfg = json.loads(SHOPS_JSON.read_text(encoding="utf-8"))["shops"]
    idx, latest = build_index()
    if not idx:
        print("没有 shop_daily 数据：先跑 scripts/fetch_lingxing.py，或手工导入 CSV")
        return 2  # 2=数据缺失，与「有预警」的 1 区分开（定时任务据此判断要不要叫人）

    as_of = max(latest.values())
    alerts = scan(idx, latest, shops_cfg, load_rules(),
                  only_shop=args.shop or None, min_level=args.min_level)
    alerts.sort(key=lambda a: (LEVEL_ORDER[a["level"]], a["shop"]))

    if args.format == "text":
        print(render_text(alerts))
    else:
        out = hr.save(render_html(alerts, as_of), OUT_DIR / ("%s_alerts.html" % as_of))
        print("✓ 预警报告 → %s" % out)
        print(render_text(alerts))

    # 退出码约定（全仓统一，见 CONTRIBUTING）：
    #   0=成功且无需处理；1=成功但有 critical/high 要人看；2=数据缺失；3+=程序错误
    return 1 if any(a["level"] in ("critical", "high") for a in alerts) else 0


if __name__ == "__main__":
    sys.exit(main())
