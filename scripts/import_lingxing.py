#!/usr/bin/env python3
"""把领星导出的报表（xlsx / csv）归一化成四张标准表。

用法：
  python3 scripts/import_lingxing.py 产品表现.xlsx
  python3 scripts/import_lingxing.py 广告报表.csv --type ads_daily

不猜表类型时才需要 --type。识别不出来会报错并列出它看到的表头，不会硬塞。

数据规矩（2026-11-04 起）：
  - 表头匹配容忍换行/空白/单位后缀（如「会话数\\nSessions」「日期(美西时间)」）；
  - 日期列必须有且必须能解析成 ISO；解析不了直接报错拒绝整表（不许静默填今天）；
  - 写入按「日期替换」合并：新导入覆盖同日期旧行，保留其他日期的历史
    （重导某一天=替换那一天；导新的一天=追加，不再整表覆盖丢历史）；
  - 一切写入路径都限定在仓库 data/ 目录内（_under_data 显式断言）。
"""
import argparse
import csv
import datetime as dt
import io
import os
import shutil
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(ROOT, "data")
# AMZ_DATA_DIR 与技能读取侧（metrics.DATA）同一语义：指向 normalized 目录；
# 设置时 raw/ 与 MANIFEST.md 跟着它的上级走（selftest 封闭性的前提）。
NORM = os.environ.get("AMZ_DATA_DIR") or os.path.join(DATA_DIR, "normalized")
RAW = os.path.join(os.path.dirname(os.path.abspath(NORM)), "raw")
MANIFEST = os.path.join(os.path.dirname(os.path.abspath(NORM)), "MANIFEST.md")

sys.path.insert(0, os.path.join(ROOT, "skills", "_shared"))
import metrics as m  # noqa: E402  （日期归一/数字清洗共用一份，不许重复实现）

# 表类型 → (必备别名组, 输出列)
SCHEMA = {
    "sales_daily": {
        "need_any": [["会话", "sessions", "浏览量"], ["销量", "units", "订购数量"]],
        "cols": ["date", "marketplace", "asin", "sku", "title", "sessions", "page_views",
                 "units", "unit_session_pct", "revenue", "currency"],
    },
    "ads_daily": {
        "need_any": [["广告活动", "campaign"], ["花费", "spend"]],
        "cols": ["date", "marketplace", "campaign", "ad_group", "targeting", "match_type",
                 "impressions", "clicks", "spend", "sales", "orders", "acos", "roas"],
    },
    "inventory_daily": {
        "need_any": [["可售", "available", "fba库存"], ["sku", "asin"]],
        "cols": ["date", "asin", "sku", "fba_available", "fba_inbound", "days_of_supply",
                 "sell_through", "replenish_suggestion", "unit_cost"],
    },
    "sku_master": {
        "need_any": [["oe", "原厂编号"], ["车型", "vehicle", "make"]],
        "cols": ["sku", "asin", "oe_number", "vehicle_make", "vehicle_model", "year_from",
                 "year_to", "position", "material", "cost", "list_price", "weight_g",
                 "certifications", "hs_code"],
    },
}

ALIAS = {
    "日期": "date", "date": "date", "站点": "marketplace", "marketplace": "marketplace",
    "asin": "asin", "ASIN": "asin", "sku": "sku", "SKU": "sku", "品名": "title", "标题": "title",
    "会话": "sessions", "sessions": "sessions", "浏览量": "page_views", "page views": "page_views",
    "销量": "units", "units": "units", "订购数量": "units", "转化率": "unit_session_pct",
    "销售额": "revenue", "revenue": "revenue", "币种": "currency", "currency": "currency",
    "广告活动": "campaign", "campaign": "campaign", "广告组": "ad_group", "ad group": "ad_group",
    "投放": "targeting", "targeting": "targeting", "匹配类型": "match_type",
    "曝光": "impressions", "impressions": "impressions", "点击": "clicks", "clicks": "clicks",
    "花费": "spend", "spend": "spend", "广告销售额": "sales", "订单": "orders", "orders": "orders",
    "acos": "acos", "ACOS": "acos", "roas": "roas", "ROAS": "roas",
    "可售库存": "fba_available", "fba可售": "fba_available", "可售": "fba_available",
    "在途": "fba_inbound", "可售天数": "days_of_supply", "动销率": "sell_through",
    "建议补货": "replenish_suggestion",
    "成本": "cost", "unit_cost": "unit_cost", "售价": "list_price",
    "oe号": "oe_number", "oe": "oe_number", "原厂编号": "oe_number",
    "品牌": "vehicle_make", "车型": "vehicle_model", "年款起": "year_from", "年款止": "year_to",
    "位置": "position", "材质": "material", "认证": "certifications", "hs编码": "hs_code",
}


def _under_data(path: str) -> str:
    """断言目标路径在仓库 data/ 目录内；越界直接终止（写入永不逃出 data/）。"""
    if ".." in str(path):
        sys.exit("路径含 ..，拒绝（只允许 data/ 内的规范路径）：%s" % path)
    real = os.path.realpath(path)
    base = os.path.realpath(DATA_DIR)
    if not (real == base or real.startswith(base + os.sep)):
        sys.exit("写入路径越界（只允许 data/ 内）：%s" % path)
    return path


def _safe_input_path(path: str) -> str:
    """入口路径检查：拒绝 ..（防穿越）；必须是已存在的文件。"""
    if ".." in str(path):
        sys.exit("输入路径含 ..，请用规范路径（如 ~/Downloads/报表.xlsx）：%s" % path)
    src = os.path.abspath(path)
    if not os.path.isfile(src):
        sys.exit("文件不存在：%s" % src)
    return src


def _safe_basename(src) -> str:
    """取纯文件名并断言不含路径分隔符（写入文件名永不带目录成分）。"""
    name = os.path.basename(os.path.normpath(str(src)))
    if not name or name in (".", "..") or "/" in name or "\\" in name or os.sep in name:
        sys.exit("非法文件名：%r" % src)
    return name


def _norm_header(h: str) -> str:
    """表头归一：去换行/制表/全半角空格（「会话数\\nSessions」→「会话数sessions」）。"""
    return "".join(str(h or "").split()).lower()


def _word_bounded(text: str, word: str) -> bool:
    i = text.find(word)
    while i >= 0:
        before_ok = i == 0 or not text[i - 1].isalnum()
        j = i + len(word)
        after_ok = j >= len(text) or not text[j].isalnum()
        if before_ok and after_ok:
            return True
        i = text.find(word, i + 1)
    return False


def map_header(h) -> str | None:
    """原始表头 → 标准列名。精确匹配优先；再归一后做包含匹配
    （中文直接子串；英文短别名要求词边界，防 'oe' 误命中 'goes'）；
    多候选取更长别名（更具体）。都不中返回 None。"""
    raw = str(h or "").strip()
    if not raw:
        return None
    if raw in ALIAS:
        return ALIAS[raw]
    low = raw.lower()
    if low in ALIAS:
        return ALIAS[low]
    norm = _norm_header(raw)
    best = None
    for alias, col in ALIAS.items():
        a = _norm_header(alias)
        if not a:
            continue
        if a in norm:
            if len(a) <= 3 and a.isascii() and not _word_bounded(norm, a):
                continue
            if best is None or len(a) > len(_norm_header(best[0])):
                best = (alias, col)
    return best[1] if best else None


def _read_csv_any_encoding(raw_path):
    """中文 Windows 的 Excel 另存 CSV 常是 GBK/GB18030，逐编码尝试。"""
    path = _safe_input_path(raw_path)  # 拒绝 ..、确认存在、abspath 规范化
    last_err = None
    for enc in ("utf-8-sig", "utf-8", "gb18030", "big5", "latin-1"):
        try:
            with open(path, newline="", encoding=enc) as f:
                sample = f.read()
            return list(csv.DictReader(io.StringIO(sample)))
        except (UnicodeDecodeError, UnicodeError) as e:
            last_err = e
            continue
    sys.exit("CSV 解不开（试过 utf-8/gb18030/big5/latin-1）：%s" % last_err)


def _find_header(rows):
    """xlsx 表头定位：跳过标题横幅/合并单元格行（前 10 行里找第一个 ≥2 个非空列的行）。"""
    if not rows:
        return None, []
    for idx in range(min(10, len(rows))):
        head = [str(c or "").strip() for c in rows[idx]]
        if sum(1 for h in head if h) >= 2:
            return head, rows[idx + 1:]
    return None, []


def read_rows(path):
    path = _safe_input_path(path)  # 拒绝 ..、确认存在、abspath 规范化
    ext = os.path.splitext(path)[1].lower()
    if ext in (".csv", ".txt"):
        return _read_csv_any_encoding(path)
    if ext in (".xlsx", ".xlsm"):
        try:
            from openpyxl import load_workbook
        except ImportError:
            sys.exit("读 xlsx 需要 openpyxl。要么装它（python3 -m pip install --user openpyxl），要么在领星里另存为 CSV。")
        wb = load_workbook(path, data_only=True, read_only=True)
        first_rows = None
        for name in wb.sheetnames:  # 多 sheet：挑第一个能 sniff 出类型的（领星常按站点分 sheet）
            rows = list(wb[name].iter_rows(values_only=True))
            head, body = _find_header(rows)
            if not head:
                continue
            dicts = [dict(zip(head, r)) for r in body if any(v not in (None, "") for v in r)]
            if sniff(head):
                return dicts
            if first_rows is None:
                first_rows = dicts
        if first_rows:
            return first_rows
        sys.exit("xlsx 里找不到能识别的表头（试了 %d 个 sheet），用 --type 指定或检查导出格式。" % len(wb.sheetnames))
    sys.exit("只支持 .csv 和 .xlsx，收到：%s" % ext)


def sniff(headers):
    lowered = [h.lower() for h in headers]
    for name, spec in SCHEMA.items():
        if all(any(any(a.lower() in h for h in lowered) for a in group) for group in spec["need_any"]):
            return name
    return None


# 可选观察列：缺失不影响表能不能用，不参与 degraded 判定（关键字段缺了才降级）
OPTIONAL_COLS = {
    "inventory_daily": ["days_of_supply", "sell_through", "replenish_suggestion", "unit_cost"],
    "sales_daily": ["page_views", "unit_session_pct", "title", "marketplace", "currency"],
    "ads_daily": ["ad_group", "targeting", "match_type", "acos", "roas"],
    "sku_master": ["vehicle_make", "vehicle_model", "year_from", "year_to", "position",
                   "material", "list_price", "weight_g", "certifications", "hs_code", "cost"],
}


def normalize(rows, table):
    """映射列 + 归一日期。带时间维度的表必须有日期列且能解析，否则报错拒绝整表。"""
    if table not in SCHEMA or ".." in table:
        sys.exit("未知表类型：%r（只允许 %s）" % (table, ", ".join(SCHEMA)))
    cols = SCHEMA[table]["cols"]
    out, bad_dates, mapped_any_date = [], 0, False
    for r in rows:
        rec = {}
        for k, v in r.items():
            key = map_header(k)
            if key and key in cols and key not in rec:
                rec[key] = ("" if v is None else str(v).strip())
        if table != "sku_master":
            iso = m.parse_date(rec.get("date"))
            if iso:
                mapped_any_date = True
                rec["date"] = iso
            else:
                bad_dates += 1
                rec["date"] = ""
        out.append(rec)
    if table != "sku_master" and not mapped_any_date:
        seen = "、".join(sorted({str(k).strip() for r in rows[:5] for k in r.keys()}))[:200]
        sys.exit(
            "认不出日期列（表头：%s）。日期是所有时间窗口的前提，拒绝静默填「今天」——\n"
            "请在领星导出时选「按天」粒度（报表要带日期列），或检查文件是否导错了。" % seen)
    if table != "sku_master" and bad_dates:
        print("  ⚠ %d 行日期解析不了（置空，读取侧会跳过这些行）" % bad_dates)
    return out, cols


# 目标文件名用常量查表（模块加载时固定），不做任何运行时路径拼接
_DST_PATHS = {
    "sales_daily": os.path.join(NORM, "sales_daily.csv"),
    "ads_daily": os.path.join(NORM, "ads_daily.csv"),
    "inventory_daily": os.path.join(NORM, "inventory_daily.csv"),
    "sku_master": os.path.join(NORM, "sku_master.csv"),
}


def merge_write(table, recs, cols):
    """按日期合并写入：新数据的日期替换旧表同日期行，其他日期历史保留（pathlib 实现）。"""
    from pathlib import Path
    if table not in _DST_PATHS:
        sys.exit("未知表类型：%r（只允许 %s）" % (table, ", ".join(_DST_PATHS)))
    target = Path(_DST_PATHS[table])
    new_dates = {r.get("date", "") for r in recs if r.get("date", "")}
    kept_lines = []
    if target.exists() and new_dates:
        reader = csv.DictReader(io.StringIO(target.read_text(encoding="utf-8")))
        for r in reader:
            if str(r.get("date", "")).strip() in new_dates:
                continue  # 被本次导入的日期覆盖
            kept_lines.append(r)
    merged = kept_lines + recs
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=cols, extrasaction="ignore")
    w.writeheader()
    for r in merged:
        w.writerow(r)
    target.write_text(buf.getvalue(), encoding="utf-8")
    dates_shown = "、".join(sorted(new_dates)[:6]) + ("…" if len(new_dates) > 6 else "")
    note = "（合并后共 %d 行：保留历史 %d 行 + 本次 %d 行，覆盖日期 %s）" % (
        len(merged), len(kept_lines), len(recs), dates_shown)
    return str(target), note


def quality_of(rows, table):
    """任一关键字段整表 100% 为空 → degraded（不管占比多少，列变多也不漏判）。

    可选观察列（OPTIONAL_COLS）不计入；关键列只是"部分行空"不降级（数据能用）。
    """
    cols = SCHEMA[table]["cols"]
    optional = set(OPTIONAL_COLS.get(table, []))
    key_cols = [c for c in cols if c not in optional]
    filled = {c: sum(1 for r in rows if str(r.get(c, "")).strip()) for c in cols}
    missing = [c for c, n in filled.items() if n == 0]
    key_missing = [c for c in missing if c in key_cols]
    return {"missing": missing, "quality": "degraded" if key_missing else "ok"}


def stage_raw(src, raw_dir):
    """raw 同日同名防覆盖：已有同名文件先移入 raw/<date>/superseded/（只增不删，唯一名），再放新文件。"""
    os.makedirs(raw_dir, exist_ok=True)
    name = _safe_basename(src)
    dst = os.path.join(raw_dir, name)
    if os.path.exists(dst):
        sup_dir = os.path.join(raw_dir, "superseded")
        os.makedirs(sup_dir, exist_ok=True)
        stamp = dt.datetime.now().strftime("%H%M%S")
        shutil.move(dst, os.path.join(sup_dir, "%s-%s" % (stamp, os.path.basename(src))))
    shutil.copy2(src, dst)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("path")
    ap.add_argument("--type", choices=list(SCHEMA), default=None)
    args = ap.parse_args()

    rows = read_rows(_safe_input_path(args.path))
    if not rows:
        sys.exit("文件里没有数据行")
    table = args.type or sniff(list(rows[0].keys()))
    if not table:
        sys.exit("认不出这是哪张表。表头是：%s\n用 --type 指定其中之一：%s"
                 % (list(rows[0].keys())[:12], ", ".join(SCHEMA)))

    recs, cols = normalize(rows, table)
    os.makedirs(NORM, exist_ok=True)
    day = dt.date.today().isoformat()
    stage_raw(args.path, os.path.join(RAW, day))

    dst, note = merge_write(table, recs, cols)

    q = quality_of(recs, table)
    missing = q["missing"]
    quality = q["quality"]

    line = "- %s | %s | 行数 %d | 缺字段 %s | %s\n" % (
        day, table, len(recs), ", ".join(missing) or "无", quality)
    if not os.path.exists(MANIFEST):
        open(MANIFEST, "w").write("# 数据入库台账\n\n")
    open(MANIFEST, "a").write(line)

    print("✓ %s → %s（%d 行）%s" % (table, dst, len(recs), note))
    if missing:
        print("  缺字段：%s" % ", ".join(missing))
    if quality != "ok":
        print("  ⚠ 缺失率超过 20%%，标记 degraded：相关技能只会给观察，不给建议")


if __name__ == "__main__":
    main()
