#!/usr/bin/env python3
"""亚马逊运维的核心口径：所有算式只在这里写一次。

各技能的脚本都调这个模块；改口径只改这里，别处不许重复实现。
纯标准库，无依赖。

口径约定：
- 金额单位与货币由调用方保证一致，本模块不做汇率换算。
- 广告的 sales 指广告归因销售额，不是店铺总销售额。
- 成本含：拿货 + 头程 + FBA 配送费 + 平台佣金 + 退货损耗。
"""
from __future__ import annotations

import csv
import datetime as dt
import json
import os
import re
from dataclasses import dataclass, asdict

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DATA = os.environ.get("AMZ_DATA_DIR") or os.path.join(ROOT, "data/normalized")

# 内置默认阈值（占位/未校准）。运行时以 config/thresholds.yaml 为准（load_thresholds 合并），
# 这里只作 yaml 读不到时的兜底；校准任务改 yaml 即可生效，不许再在技能里写死。
MIN_CLICKS_FOR_JUDGEMENT = 8
ROOT_MIN_CLICKS_FOR_JUDGEMENT = 12
NEGATIVE_MIN_CLICKS = 2
HIGH_SPEND_WITHOUT_ORDER = 15.0     # 花费超过这个数且 0 单，必须处理
DEFAULT_DOS_ALERT = 21              # 可售天数低于这个值报警
DEFAULT_ACOS_TOLERANCE = 0.15       # 高于盈亏平衡 ACOS 15% 以内算正常波动

_THRESHOLD_CACHE: dict | None = None


def thresholds() -> dict:
    """读 thresholds.yaml（模块级缓存；文件不存在时返回内置默认并带 _warning）。

    decide_term / evaluate_ads 等决策函数都从这里取数——校准任务改 yaml，
    不改代码，闭环才真正连得上。
    """
    global _THRESHOLD_CACHE
    if _THRESHOLD_CACHE is None:
        _THRESHOLD_CACHE = load_thresholds()
    return _THRESHOLD_CACHE


def _ads_cfg() -> dict:
    return thresholds().get("ads", {}) or {}


# ---------- 数字清洗（领星导出的真实格式：$1,234.56 / 12.3% / (123) / USD 45） ----------

_CURRENCY_WORDS = ("usd", "cad", "mxn", "brl", "rmb", "eur", "jpy", "gbp", "us$", "c$", "a$", "r$", "£", "€", "$", "$")
_MISSING_TOKENS = {"", "-", "—", "–", "n/a", "na", "null", "none", "nil", "暂无", "无", "待补"}
_PLAIN_NUM_RE = re.compile(r"\d+(?:\.\d+)?")


def _clean_number(x) -> float | None:
    """把领星/Excel 导出的脏数字清洗成 float；解析不了返回 None（缺数），绝不返回 0 冒充。

    支持：'$1,234.56'、'1,234'、'12.3%'（→0.123）、'(123)'（→-123）、'USD 45'、'-5.0'。
    百分号语义：带 % 一律视为百分比，除以 100。
    """
    if x is None:
        return None
    if isinstance(x, bool):
        return None
    if isinstance(x, (int, float)):
        return float(x)
    s = str(x).strip()
    if s.lower() in _MISSING_TOKENS:
        return None
    neg = False
    if s.startswith("(") and s.endswith(")"):        # 会计负数 (123)
        neg, s = True, s[1:-1].strip()
    s = s.replace(",", "").replace("，", "").replace(" ", "").replace("\u00a0", "")
    low = s.lower()
    for w in _CURRENCY_WORDS:
        if low.startswith(w):
            s, low = s[len(w):], low[len(w):]
        if low.endswith(w):
            s, low = s[:-len(w)], low[:-len(w)]
    if s.startswith("-"):
        neg, s = (not neg), s[1:]
    elif s.startswith("+"):
        s = s[1:]
    pct = s.endswith("%")
    s = s.rstrip("%")
    if not _PLAIN_NUM_RE.fullmatch(s):
        return None
    v = float(s)
    if pct:
        v /= 100.0
    if neg:
        v = -v
    return v if v == v else None  # NaN 防御（v!=v 即 NaN）


def _f(x, default=0.0):
    v = _clean_number(x)
    return default if v is None else v


def num(x) -> float | None:
    """区分「缺数」与 0 的读取：解析不了返回 None，调用方跳过或标 needs_data。"""
    return _clean_number(x)


def load(table: str) -> list[dict]:
    """读 data/normalized/<table>.csv；不存在返回空列表（由调用方判 needs_data）。"""
    path = os.path.join(DATA, table + ".csv")
    if not os.path.exists(path):
        return []
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


# ---------- 基础算式 ----------
#
# 【调用方式说明：别把这些当死代码删掉】
# contribution_margin / breakeven_acos / unit_profit / inventory_turnover / price_floor /
# decide_term / evaluate_ads 这些**没有脚本 import 点**，是设计如此：
# amz-ads-diagnose 没有 run.py，它是一套诊断流程，由 AI 现场调这些函数算、
# 再按流程给处置建议（见该技能 SKILL.md「高级规则」）；校准与成本模型也会调。
# 判断"能不能删"看 SKILL.md 有没有引用，不看有没有 import。
# 改本节任何函数前先跑 `python3 skills/_shared/test_metrics.py`（44 项断言）。
#

def acos(spend: float, sales: float) -> float | None:
    """广告花费效率。sales=0 时无意义，返回 None（不要返回 0 冒充好成绩）。"""
    if sales <= 0:
        return None
    return spend / sales


def roas(spend: float, sales: float) -> float | None:
    if spend <= 0:
        return None
    return sales / spend


def contribution_margin(price: float, unit_cost: float, freight: float, fba_fee: float,
                        commission_rate: float, return_rate: float = 0.0,
                        return_loss_ratio: float = 1.0) -> float:
    """贡献毛利（绝对值）。退货损耗按"退货率 × 货值 × 损耗比"扣。"""
    commission = price * commission_rate
    loss = price * return_rate * return_loss_ratio
    return price - unit_cost - freight - fba_fee - commission - loss


def breakeven_acos(price: float, unit_cost: float, freight: float, fba_fee: float,
                   commission_rate: float, return_rate: float = 0.0) -> float | None:
    """盈亏平衡 ACOS = 贡献毛利 ÷ 售价。ACOS 低于它就是赚，高于就是亏。"""
    if price <= 0:
        return None
    cm = contribution_margin(price, unit_cost, freight, fba_fee, commission_rate, return_rate)
    return cm / price


def unit_profit(price: float, unit_cost: float, freight: float, fba_fee: float,
                commission_rate: float, ad_spend: float, units: float,
                return_rate: float = 0.0) -> float | None:
    """单件净利 = 贡献毛利 − 广告分摊。"""
    if units <= 0:
        return None
    cm = contribution_margin(price, unit_cost, freight, fba_fee, commission_rate, return_rate)
    return cm - ad_spend / units


def days_of_supply(fba_available: float, units_last_28d: float, window_days: int = 28) -> float | None:
    """可售天数。没有销量（新品）返回 None，不要除以 0 得出无穷大。"""
    daily = units_last_28d / float(window_days)
    if daily <= 0:
        return None
    return fba_available / daily


def inventory_turnover(avg_inventory_units: float, cogs_last_30d: float, avg_unit_cost: float) -> float | None:
    """库存周转次数（30 天）。用件数算，避免不同 SKU 单价差异污染。"""
    if avg_inventory_units <= 0 or avg_unit_cost <= 0:
        return None
    return cogs_last_30d / (avg_inventory_units * avg_unit_cost)


def ad_contribution(sales: float, spend: float, margin_rate: float) -> float:
    """广告贡献毛利 = 销售额 × 毛利率 − 花费。比单看 ACOS 靠谱。"""
    return sales * margin_rate - spend


def price_floor(unit_cost: float, freight: float, fba_fee: float, commission_rate: float,
                min_margin_rate: float) -> float:
    """价格下限：任何改价建议都不许低于它。"""
    fixed = unit_cost + freight + fba_fee
    return fixed / max(1e-9, (1 - commission_rate - min_margin_rate))


def return_rate(returned_units: float, shipped_units: float) -> float | None:
    if shipped_units <= 0:
        return None
    return returned_units / shipped_units


def cvr(units: float, sessions: float) -> float | None:
    if sessions <= 0:
        return None
    return units / sessions


# ---------- 日期归一与时间窗口（导入器与技能共用；不归一，排序/窗口全是空谈） ----------

_DATE_RE = re.compile(r"(\d{4})[-/.年](\d{1,2})[-/.月](\d{1,2})日?")
_EXCEL_SERIAL_RE = re.compile(r"\d{5}(?:\.0)?")


def parse_date(v) -> str | None:
    """把领星/Excel 的各种日期形态归一成 ISO yyyy-mm-dd；解析不了返回 None。

    支持：'2026-11-04'、'2026/11/4'、'2026年11月4日'、'2026-11-03 00:00:00'（截日期）、
    Excel 序列数（1900 体系，openpyxl data_only=False 或纯数字单元格）。
    """
    if v is None:
        return None
    if isinstance(v, dt.datetime):
        return v.date().isoformat()
    if isinstance(v, dt.date):
        return v.isoformat()
    s = str(v).strip()
    if not s:
        return None
    if _EXCEL_SERIAL_RE.fullmatch(s):
        try:
            return (dt.date(1899, 12, 30) + dt.timedelta(days=int(float(s)))).isoformat()
        except (OverflowError, ValueError):
            return None
    m = _DATE_RE.match(s)
    if m:
        try:
            return dt.date(int(m.group(1)), int(m.group(2)), int(m.group(3))).isoformat()
        except ValueError:
            return None
    return None


def row_date(r: dict) -> str | None:
    """一行的 date 字段归一成 ISO（兼容 '2026-11-03 00:00:00' 尾巴）。"""
    return parse_date(r.get("date")) or _date_loose(r.get("date"))


def _date_loose(v):
    """parse_date 不认但形如 'YYYY-MM-DD…' 的，截前 10 位再试。"""
    if v is None:
        return None
    s = str(v).strip()
    return s[:10] if len(s) >= 10 and s[4] in "-/." and s[:4].isdigit() else None


def table_dates(rows: list[dict]) -> list[str]:
    """表内出现的全部 ISO 日期（去重升序）。"""
    ds = {row_date(r) for r in rows}
    ds.discard(None)
    return sorted(ds)


def latest_rows(rows: list[dict], days: int = 1) -> list[dict]:
    """取表内最新 days 天的行（date 已归一前提下按字符串比较）。"""
    ds = table_dates(rows)
    if not ds:
        return list(rows)
    keep = set(ds[-days:] if days > 0 else ds)
    return [r for r in rows if row_date(r) in keep]


def table_date_span(rows: list[dict]) -> int | None:
    """表内最早到最新日期隔了多少天（None=没有可认的日期）。"""
    ds = table_dates(rows)
    if len(ds) < 2:
        return None if not ds else 0
    d0 = dt.date.fromisoformat(ds[0])
    d1 = dt.date.fromisoformat(ds[-1])
    return (d1 - d0).days + 1


def adjacency_gap(rows: list[dict]) -> int | None:
    """最后两个有数据的日期隔了几天（>1 说明有断档，骤涨骤跌的比较要打问号）。"""
    ds = table_dates(rows)
    if len(ds) < 2:
        return None
    return (dt.date.fromisoformat(ds[-1]) - dt.date.fromisoformat(ds[-2])).days


def rows_in_month(rows: list[dict], month: str) -> list[dict]:
    """取 date 在某月（'2026-11'）内的行。"""
    return [r for r in rows if (row_date(r) or "").startswith(month)]


def sales_anomalies(rows: list[dict], drop_ratio: float = 0.5, spike_ratio: float = 1.0):
    """相邻两天同 SKU 销量骤变排查（每日任务，只读）。

    只拿 sales_daily 里按日期排序后最相邻的两个日期比：前一天→最新一天。
    - 最新比前一天跌超 drop_ratio → "drop"（骤跌，要查差评/掉排名/竞对降价）
    - 最新比前一天涨超 spike_ratio → "spike"（骤涨，要确认是不是异常单/跟卖单）
    - 前一天为 0、最新 > 0 → "launch"（零销量后出单，单列提示；不推断为新品）
    窗口外的日期一律不算；只有一天数据的 SKU 不报。
    返回 [(key, prev_units, latest_units, kind)]，按 key 排序。
    """
    by_date: dict[str, dict[str, float]] = {}
    for r in rows:
        d = row_date(r)
        k = r.get("sku") or r.get("asin")
        if not d or not k:
            continue
        day = by_date.setdefault(d, {})
        day[k] = day.get(k, 0.0) + _f(r.get("units"))
    dates = sorted(by_date)
    if len(dates) < 2:
        return []
    prev_day, last_day = dates[-2], dates[-1]
    out = []
    for k, latest in sorted(by_date[last_day].items()):
        prev = by_date[prev_day].get(k)
        if prev is None:
            continue
        if prev <= 0:
            if latest > 0:
                out.append((k, prev, latest, "launch"))
            continue
        change = (latest - prev) / prev
        if change <= -drop_ratio:
            out.append((k, prev, latest, "drop"))
        elif change >= spike_ratio:
            out.append((k, prev, latest, "spike"))
    return out


# ---------- 车标硬阻断（用户定义的侵权红线，A9） ----------
#
# 【2026-11-04 维护者 定调，规则按介质分两种，不要混】
#   图片（image）：绝对不许出现车标/徽标/方向盘标/轮毂中心盖/水印 logo —— 命中即 HOLD。
#   文字/广告（text）：**允许**出现车品牌名（Honda/Toyota…）和车型名（Accord/Camry…），
#                      这是 fitment 与搜索承接的必需品；只有"把车标当创意元素"的表述
#                      （如"车标风格贴纸""带 logo 的副图"）才 HOLD。
# 所以本函数吃 context 参数：image 走严格模式，text 走宽松模式（品牌/车型名永不命中）。

# 触发词 = 文案/元数据里"把车标当创意元素用"的表述（image 与 text 共用这份底线）
VEHICLE_LOGO_TRIGGERS = (
    "车标", "徽标", "方向盘标", "轮毂标", "轮毂中心盖", "车标水印",
    "vehicle emblem", "car logo", "steering wheel logo", "hub cap logo",
    "brand badge", "logo",
)

# 图片侧额外严格项：任何与"品牌标识出现在画面上"相关的表述都拦
IMAGE_STRICT_TRIGGERS = VEHICLE_LOGO_TRIGGERS + (
    "品牌标识", "车辆标识", "品牌标", "brand mark", "trademark", "商标", "原厂标识")


# 触发词紧邻的否定语境（出现这些词说明是"声明没有车标"而不是"要用车标"，不算命中）。
# 中文否定要求"紧贴"触发词（如"无车标"）；"无边框车标"里的"无"否定的是"边框"，不算豁免。
VEHICLE_LOGO_NEGATIONS = ("无", "不含", "没有", "不带", "不包含", "无需", "非")
_EN_NEG_RE = re.compile(r"(?<![a-z])(without|with no|no|not|none|non)(?![a-z])")
_POST_NEG_RE = re.compile(r"^[\s\-–—/]?(free|none|less)")


def _logo_negated(t: str, i: int, ln: int) -> bool:
    """触发词是否处于否定语境。中文看紧贴前置，英文看前置词边界 + 后置 free/none。"""
    before = t[max(0, i - 25):i]
    after = t[i + ln: i + ln + 12]
    for neg in VEHICLE_LOGO_NEGATIONS:
        j = before.rfind(neg)
        if j >= 0 and before[j + len(neg):].strip() == "":
            return True
    if _EN_NEG_RE.search(before):
        return True
    if _POST_NEG_RE.match(after):
        return True
    return False


def brand_logo_hold(text: str, context: str = "text") -> list[str]:
    """车标 HOLD 判定。返回命中列表（非空 = HOLD，不得给可发布结论）。

    context="image"（图片/副图/Fitment 卡片）：严格——任何车标相关表述都 HOLD，
        因为图片侧不允许出现车标（2026-11-04 定调，绝对红线）。
    context="text"（Listing 文案/广告/搜索词）：宽松——品牌名（Honda/Toyota）与车型名
        （Accord/Camry/Model Y）**允许出现**，只有"把车标当创意元素用"的表述才 HOLD。
        这是 fitment 与搜索承接的必需品，卡死品牌车型名等于让运营没法写标题。

    否定语境豁免（两种 context 都适用）：
    - 中文：否定词紧贴触发词（"无车标""不带 logo"）才豁免；"无边框车标"不豁免；
    - 英文：触发词前 25 字符内出现 without/no/not/none（词边界）豁免（"without any car logo"）；
    - 后置否定：紧跟 free/none（"logo free design"）豁免。
    """
    triggers = IMAGE_STRICT_TRIGGERS if context == "image" else VEHICLE_LOGO_TRIGGERS
    t = (text or "").lower()
    hits = []
    for p in triggers:
        needle = p.lower()
        start = 0
        while True:
            i = t.find(needle, start)
            if i < 0:
                break
            if _logo_negated(t, i, len(needle)):
                start = i + len(needle)
                continue
            hits.append(p)
            break
    return hits


# 品牌名/车型名白名单（仅用于给运营解释"为什么这些不算 HOLD"，不参与拦截逻辑）
BRAND_NAMES_ALLOWED_IN_TEXT = (
    "honda", "toyota", "ford", "chevrolet", "chevy", "nissan", "bmw", "mercedes", "benz",
    "audi", "vw", "volkswagen", "hyundai", "kia", "mazda", "subaru", "jeep", "dodge",
    "lexus", "acura", "infiniti", "tesla", "volvo", "peugeot", "renault", "fiat",
    "accord", "camry", "civic", "corolla", "cr-v", "rav4", "altima", "sentra", "model y",
    "model 3", "f150", "f-150", "silverado", "explorer", "escape", "elantra", "sonata",
    "qx60", "pathfinder", "murano", "maxima", "tahoe", "suburban", "wrangler", "cherokee",
)


def text_brand_mentions(text: str) -> list[str]:
    """列出文案里出现的品牌/车型名（用于报告"品牌名可写"的说明，不做拦截）。"""
    t = (text or "").lower()
    return [b for b in BRAND_NAMES_ALLOWED_IN_TEXT if b in t]


# ---------- 汽配词根：fitment 长尾靠词根继承 ----------

YEAR_RE = r"(19|20)\d{2}"
MAKES = ("honda", "toyota", "ford", "chevrolet", "chevy", "nissan", "bmw", "benz", "mercedes",
         "audi", "vw", "volkswagen", "hyundai", "kia", "mazda", "subaru", "jeep", "dodge",
         "lexus", "acura", "infiniti", "tesla", "volvo", "peugeot", "renault", "fiat")


def keyword_root(term: str) -> str:
    """把「front brake pads for 2015 honda accord」压成「front brake pads」。

    规则：去掉年款（19xx/20xx）与其后的品牌/车型词，保留部件描述作为词根。
    """
    import re

    t = term.lower().strip()
    # 截断在 for / fits / compatible with 之后
    cut = re.split(r"\b(for|fits|compatible with|fit)\b", t)[0].strip()
    words = cut.split()
    kept = [w for w in words if not re.search(YEAR_RE, w) and w not in MAKES]
    return " ".join(kept) if kept else t


@dataclass
class TermDecision:
    term: str
    decision: str          # keep / watch / negative / pool
    basis: str             # term / root / pool
    confidence: str        # high / medium / low / needs_data
    reason: str


def decide_term(term: str, clicks: float, orders: float, spend: float,
                root_clicks: float | None = None) -> TermDecision:
    """搜索词决策：词自身样本够就按词判，不够继承词根，词根也不够进长尾池。

    pool 是一种决策（"不逐词判"），不是未决，所以不计入 needs_data。
    阈值（min_clicks / high_spend_no_order 等）全部从 config/thresholds.yaml 的 ads 段读，
    校准任务改 yaml 即生效；有订单但单均花费（CPA）超阈值的词降为 watch 人工复核，
    不再无条件 keep。
    """
    cfg = _ads_cfg()
    min_clicks = cfg.get("min_clicks_for_judgement", MIN_CLICKS_FOR_JUDGEMENT)
    root_min = cfg.get("root_min_clicks_for_judgement", ROOT_MIN_CLICKS_FOR_JUDGEMENT)
    neg_min = cfg.get("negative_min_clicks", NEGATIVE_MIN_CLICKS)
    high_spend = cfg.get("high_spend_no_order", HIGH_SPEND_WITHOUT_ORDER)

    if clicks >= min_clicks:
        if orders <= 0 and spend >= high_spend:
            return TermDecision(term, "negative", "term", "high", "花费 %.1f 无订单" % spend)
        if orders > 0:
            cpa = spend / orders
            if cpa > high_spend:
                return TermDecision(term, "watch", "term", "medium",
                                    "有订单但 CPA %.1f 超阈值 %.1f，先查 Listing/价格再决定去留" % (cpa, high_spend))
            return TermDecision(term, "keep", "term", "medium",
                                "有点击有订单，CPA %.1f 在阈值内" % cpa)
        return TermDecision(term, "watch", "term", "medium", "样本刚够，先观察")

    if root_clicks is not None and root_clicks >= root_min:
        if orders <= 0 and spend >= high_spend:
            return TermDecision(term, "negative", "root", "medium", "词根样本够，本词花费高无单")
        return TermDecision(term, "watch", "root", "low", "单词样本不足，继承词根判断")

    if clicks >= neg_min and orders <= 0 and spend >= high_spend:
        return TermDecision(term, "negative", "term", "low", "低样本但高花费无单，先压价观察")

    return TermDecision(term, "pool", "pool", "needs_data", "单词与词根样本都不足，归入长尾池汇总监控")


# ---------- 数据可用性 ----------

def data_status(table: str) -> dict:
    """判断一张表能不能用于出建议。缺字段过多或没数据 → 只能出观察。"""
    rows = load(table)
    if not rows:
        return {"table": table, "rows": 0, "usable": False, "reason": "没有数据，先导入"}
    cols = list(rows[0].keys())
    filled = {c: sum(1 for r in rows if str(r.get(c, "")).strip()) for c in cols}
    missing = [c for c, n in filled.items() if n == 0]
    ratio = len(missing) / max(len(cols), 1)
    usable = ratio <= 0.2
    return {"table": table, "rows": len(rows), "usable": usable,
            "missing": missing, "missing_ratio": round(ratio, 3)}


def evaluate_ads(row: dict, margin_rate: float) -> dict:
    """一行广告数据的体检结果。容忍度阈值从 thresholds.yaml 的 ads 段读。"""
    spend, sales = _f(row.get("spend")), _f(row.get("sales"))
    orders, clicks = _f(row.get("orders")), _f(row.get("clicks"))
    a = acos(spend, sales)
    tolerance = _ads_cfg().get("acos_tolerance_over_breakeven", DEFAULT_ACOS_TOLERANCE)
    out = {
        "campaign": row.get("campaign") or row.get("ad_group") or "",
        "spend": spend, "sales": sales, "orders": orders, "clicks": clicks,
        "acos": None if a is None else round(a, 4),
        "ad_contribution": round(ad_contribution(sales, spend, margin_rate), 2),
    }
    if a is None and spend > 0:
        out["verdict"] = "有花费无销售额"
    elif a is not None and a > margin_rate * (1 + tolerance):
        out["verdict"] = "ACOS 高于盈亏平衡线"
    elif a is not None and a <= margin_rate:
        out["verdict"] = "在盈亏线内"
    else:
        out["verdict"] = "接近盈亏线，观察"
    return out


def to_dict(obj):
    return asdict(obj) if hasattr(obj, "__dataclass_fields__") else obj

def _parse_simple_yaml(text: str) -> dict:
    """解析本仓库 config/*.yaml 这种受限 YAML：两级 map、标量值、# 注释、"- " 序列（map 项或纯字符串项）。

    仓库契约是纯标准库无依赖（见本模块开头），所以不 import yaml；
    结构超出这个范围（深层嵌套、锚点、多行块）时直接报错，逼配置先简化。
    """
    root: dict = {}
    section = None
    item = None  # 当前序列项（dict 或纯字符串）
    for raw in text.splitlines():
        line = raw.split("#", 1)[0].rstrip()
        if not line.strip():
            continue
        stripped = line.strip()
        indented = line.startswith((" ", "\t"))
        if stripped.startswith("- "):
            if section is None:
                raise ValueError("序列没有归属分组：%r" % raw)
            bucket = root.get(section)
            if not isinstance(bucket, list):
                bucket = []
                root[section] = bucket
            content = stripped[2:].strip()
            k, _, v = content.partition(":")
            item = {k.strip(): _scalar(v.strip())} if _ else content
            bucket.append(item)
            continue
        key, _, value = line.partition(":")
        if not _:
            if isinstance(item, str):  # 纯字符串序列项的续行
                item += " " + stripped
                continue
            raise ValueError("阈值表只能是 key: value 两行结构：%r" % raw)
        key = key.strip()
        value = value.strip()
        if not indented:
            item = None
            section = key
            root[section] = {} if value == "" else _scalar(value)
        else:
            if section is None:
                raise ValueError("缩进行没有归属分组：%r" % raw)
            if isinstance(root.get(section), list):
                if isinstance(item, dict):
                    item[key] = _scalar(value)
                else:
                    raise ValueError("序列项内只能是 key: value：%r" % raw)
            else:
                if not isinstance(root.get(section), dict):
                    root[section] = {}
                root[section][key] = _scalar(value)
    return root


def _scalar(s: str):
    if s == "":
        return None
    if s.strip().lower() in ("null", "~"):
        return None
    try:
        return int(s)
    except ValueError:
        try:
            f = float(s)
            return f
        except ValueError:
            return s.strip('"').strip("'")


def load_automations_config(path: str | None = None) -> dict:
    """读 config/automations.yaml（纯标准库解析，无 PyYAML 依赖）。"""
    p = path or os.path.join(ROOT, "config", "automations.yaml")
    with open(p, encoding="utf-8") as f:
        return _parse_simple_yaml(f.read())


# ---------- 导入质量（MANIFEST 台账可读，不只写） ----------

def import_quality(table: str, manifest_path: str | None = None) -> dict | None:
    """读 data/MANIFEST.md 里该表最新一次导入行：{date, rows, missing, quality}。

    quality ∈ ok/degraded；没导过该表返回 None。degraded 时下游技能只出观察、不出建议。
    """
    p = manifest_path or os.path.join(os.path.dirname(DATA), "MANIFEST.md")
    best = None
    try:
        with open(p, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line.startswith("- "):
                    continue
                parts = [s.strip() for s in line[2:].split("|")]
                if len(parts) < 5 or parts[1] != table:
                    continue
                missing_raw = parts[3].replace("缺字段", "").strip()
                missing = "" if missing_raw in ("无", "") else missing_raw
                best = {
                    "date": parts[0],
                    "rows": int("".join(c for c in parts[2] if c.isdigit()) or 0),
                    "missing": [x.strip() for x in missing.split(",") if x.strip()],
                    "quality": parts[4],
                }
    except OSError:
        return None
    return best


def degraded_tables(names: list) -> list:
    """这些表里哪些上次导入是 degraded，返回 [(table, quality_row), ...]。"""
    out = []
    for t in names:
        q = import_quality(t)
        if q and q.get("quality") == "degraded":
            out.append((t, q))
    return out


def load_thresholds(path: str | None = None) -> dict:
    """读 config/thresholds.yaml（纯标准库解析）；读不到就用完整内置默认值并打未校准警告。

    内置默认值是"占位/行业候选"，不是公司校准值；任何脚本拿到 _warning 时
    都应知道这些数字没经过自己数据验证。
    """
    p = path or os.path.join(ROOT, "config/thresholds.yaml")
    defaults = {
        "stockout": {"sales_window_days": 28, "days_of_supply_alert": 21, "days_of_supply_critical": 10,
                     "low_stock_ratio_vs_28d": 28, "calibration_status": "未校准"},
        "store_stock": {"sales_window_days": 7, "days_of_supply_alert": 14, "calibration_status": "未校准"},
        "competitor": {"price_change_ratio": 0.03, "bsr_change_ratio": 0.30,
                       "rating_drop": 0.2, "gap_widen_usd": 5.0,
                       "gap_widen_ratio": 0.05, "calibration_status": "未校准"},
        "ads": {"acos_tolerance_over_breakeven": 0.15, "high_spend_no_order": 15.0,
                "min_days_window": 7, "min_clicks_for_judgement": 8,
                "root_min_clicks_for_judgement": 12, "negative_min_clicks": 2,
                "calibration_status": "未校准"},
        "sales": {"daily_drop_ratio": 0.50, "daily_spike_ratio": 1.00,
                  "calibration_status": "未校准"},
        "listing": {"title_min_chars": 80, "title_max_chars": 200, "bullet_count_min": 5,
                    "bullet_max_chars": 500, "description_min_chars": 200,
                    "main_image_min_side": 2000, "product_fill_ratio_min": 0.85,
                    "calibration_status": "未校准"},
        "fitment": {"min_oe_ratio": 0.90, "min_year_ratio": 0.90, "calibration_status": "未校准"},
        "data": {"max_age_days": 3, "missing_ratio_limit": 0.20, "calibration_status": "不适用"},
        "calibration": {"confirm_hits_to_promote": 3, "refutes_to_demote": 2,
                        "min_hit_rate": 0.50, "calibration_status": "不适用"},
    }
    try:
        with open(p, encoding="utf-8") as f:
            got = _parse_simple_yaml(f.read())
        for k, v in defaults.items():
            got.setdefault(k, v)
            if isinstance(v, dict):
                for kk, vv in v.items():
                    got[k].setdefault(kk, vv)
        return got
    except OSError:
        defaults["_warning"] = "阈值表读不到（%s），用内置占位默认值，未经校准" % p
        return defaults


def recent_units_by_sku(rows, days=28, as_of=None):
    """近 N 天窗口内每个 SKU 的等效 N 天销量（库存可售天数专用）。

    为什么不能用全表跨度：sales_daily 可能含去年同期回补段，
    全表跨度会被拉成几百天，把日均销量稀释、库存预警失真。
    这里固定取「最新数据日（不含今天）」往前 N 天，窗口内求和；
    窗口实际覆盖不足 N 天时按实际天数折算成 N 天等效。
    """
    import datetime as _dt
    dated = [(row_date(r), r) for r in rows]
    dated = [(d, r) for d, r in dated if d]
    if not dated:
        return {}
    latest = as_of or max(d for d, _ in dated)
    end = _dt.date.fromisoformat(latest)
    start = (end - _dt.timedelta(days=days - 1)).isoformat()
    out = {}
    actual_days = set()
    for d, r in dated:
        if start <= d <= latest:
            k = r.get("sku") or r.get("asin")
            out[k] = out.get(k, 0.0) + _f(r.get("units"))
            actual_days.add(d)
    span = max(len(actual_days), 1)
    factor = float(days) / span if span < days else 1.0
    return {k: v * factor for k, v in out.items()}


def inventory_policy(scope="sku", config=None):
    """统一库存口径但保留粒度差异：SKU 28 天分档，店级 7 天风险提示。"""
    cfg = config if config is not None else load_thresholds()
    if scope == "store":
        s = cfg.get("store_stock", {})
        return {"window": int(s.get("sales_window_days", 7)),
                "risk": int(s.get("days_of_supply_alert", 14))}
    s = cfg.get("stockout", {})
    return {"window": int(s.get("sales_window_days", 28)),
            "critical": int(s.get("days_of_supply_critical", 10)),
            "watch": int(s.get("days_of_supply_alert", 21)),
            "candidate": int(s.get("low_stock_ratio_vs_28d", 28))}


def competitor_policy(config=None):
    cfg = config if config is not None else load_thresholds()
    c = cfg.get("competitor", {})
    return {"price": float(c.get("price_change_ratio", 0.03)),
            "bsr": float(c.get("bsr_change_ratio", 0.30)),
            "rating": float(c.get("rating_drop", 0.2)),
            "gap_usd": float(c.get("gap_widen_usd", 5.0)),
            "gap_ratio": float(c.get("gap_widen_ratio", 0.05))}


def stock_business_state(available, units_in_window):
    """业务状态与采购动作分离；零销量可能是新品或停售，不能自动推断补货。"""
    if units_in_window <= 0:
        return "无近28天销量（新品/停售待确认）"
    if available <= 0:
        return "已断货"
    return "在库将断货"


def next_fetch_status(previous, kind, ok, rows=0, min_date="", max_date="", error="", now=None):
    """生成下一次拉取状态；保留最近成功点并累计连续失败次数。"""
    now = now or dt.datetime.now()
    previous = previous if isinstance(previous, dict) else {}
    old_sources = previous.get("sources") if isinstance(previous.get("sources"), dict) else {}
    old = old_sources.get(kind) if isinstance(old_sources.get(kind), dict) else {}
    status = "success" if ok else "failed"
    row = {
        "kind": kind, "status": status, "attempted_at": now.isoformat(timespec="seconds"),
        "rows": rows, "min_date": min_date, "max_date": max_date,
        "error": str(error)[:300] if error else "",
        "consecutive_failures": 0 if ok else int(old.get("consecutive_failures") or 0) + 1,
        "last_success_at": now.isoformat(timespec="seconds") if ok else old.get("last_success_at", ""),
        "last_success_date": max_date if ok else old.get("last_success_date", ""),
    }
    sources = {k: dict(v) for k, v in old_sources.items() if isinstance(v, dict)}
    sources[kind] = row
    return {"updated_at": now.isoformat(timespec="seconds"), "sources": sources}


def write_fetch_status(name, ok, detail="", rows=0, min_date="", max_date="", error=""):
    """向后兼容旧调用，同时写入可供预警消费的结构化拉取状态。"""
    try:
        path = os.path.join(ROOT, "data", "logs", "fetch_status.json")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        previous = {}
        if os.path.exists(path):
            try:
                with open(path, encoding="utf-8") as f:
                    previous = json.load(f)
            except (OSError, json.JSONDecodeError):
                previous = {}
        data = next_fetch_status(previous, name, ok, rows, min_date, max_date, error or ("" if ok else detail))
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, path)
    except Exception:
        pass  # 状态记录失败不掩盖主任务结果


def data_freshness(lag_days, fetch_status=None, today=None):
    """T+1 裁决：日期滞后与真实拉取结果必须同时看。"""
    fetch_status = fetch_status if isinstance(fetch_status, dict) else {}
    status = fetch_status.get("status") or "unknown"
    if status == "failed":
        count = int(fetch_status.get("consecutive_failures") or 1)
        error = fetch_status.get("error") or "未记录错误详情"
        return {"state": "fetch_failed", "level": "high",
                "message": "已连续 %d 次拉取失败（%s）；最后成功日期 %s。请查定时任务、网络与授权，不是官方未产出。" % (
                    count, error, fetch_status.get("last_success_date") or "未知")}
    if today is not None and fetch_status.get("attempted_at"):
        try:
            attempted = dt.datetime.fromisoformat(str(fetch_status["attempted_at"])).date()
            if attempted < today:
                status = "unknown"
        except ValueError:
            status = "unknown"
    if lag_days <= 1:
        return {"state": "normal", "level": "low", "message": "最新数据为昨天，符合 T+1。"}
    if lag_days == 2 and status == "success":
        return {"state": "official_delay", "level": "low",
                "message": "最近拉取成功，但昨日数据尚未出现；更像领星/官方延迟，明日复查。"}
    if status == "success":
        return {"state": "official_stale", "level": "high",
                "message": "最近拉取成功，但数据已连续 %d 天未更新；疑似上游未产出，请向领星/亚马逊核查。" % lag_days}
    return {"state": "status_unknown", "level": "high" if lag_days >= 3 else "low",
            "message": "数据已 %d 天未更新，且没有当天有效拉取状态；先补跑 fetch 并检查运行医生，不能断言是官方延迟。" % lag_days}
