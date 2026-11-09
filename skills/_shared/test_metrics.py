#!/usr/bin/env python3
"""口径模块的单测：跑 `python3 mcp/test_metrics.py`，全绿才算改对了。

每个断言都写明"为什么是这个数"，避免以后被人随手改歪。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import metrics as m  # noqa: E402

ok = 0


def check(name, got, want, tol=1e-6):
    global ok
    if want is None:
        assert got is None, "%s：期望 None，得到 %r" % (name, got)
    else:
        assert got is not None and abs(got - want) <= tol, "%s：期望 %r，得到 %r" % (name, want, got)
    ok += 1
    print("  ✓ %s = %r" % (name, got))


def main():
    global ok
    print("基础算式")

    # 花 30、卖 100 → ACOS 30%
    check("acos(30,100)", m.acos(30, 100), 0.30)
    # 无销售额时不许返回 0（0 会被误读成"极好"）
    check("acos(30,0)", m.acos(30, 0), None)
    # ROAS 100/30
    check("roas(30,100)", m.roas(30, 100), 100 / 30, 1e-9)

    # 售价 30，拿货 10，头程 2，FBA 4，佣金 15% → 贡献毛利 = 30-10-2-4-4.5 = 9.5
    check("contribution_margin", m.contribution_margin(30, 10, 2, 4, 0.15), 9.5)
    # 盈亏平衡 ACOS = 9.5/30 ≈ 31.67%
    check("breakeven_acos", m.breakeven_acos(30, 10, 2, 4, 0.15), 9.5 / 30)
    # 单件净利：广告花 20 卖 10 件 → 9.5 - 2 = 7.5
    check("unit_profit", m.unit_profit(30, 10, 2, 4, 0.15, 20, 10), 7.5)

    # 退货 10% 时毛利少 3（退货损耗按售价计）
    check("contribution_margin_with_returns",
          m.contribution_margin(30, 10, 2, 4, 0.15, 0.10), 9.5 - 3.0)

    # 价格下限：固定成本 16，佣金 15%，最低毛利 20% → 16/(1-0.35) ≈ 24.615
    check("price_floor", m.price_floor(10, 2, 4, 0.15, 0.20), 16 / 0.65)

    print("库存与流量")
    # 28 天卖 280 件 → 日均 10，库存 100 → 可售 10 天（低于 21 天该报警）
    check("days_of_supply", m.days_of_supply(100, 280), 10.0)
    # 没销量不许算出 inf
    check("days_of_supply_no_sales", m.days_of_supply(100, 0), None)
    # 周转：月销成本 3000，平均库存 100 件 × 单价 20 = 2000 → 1.5 次/月
    check("inventory_turnover", m.inventory_turnover(100, 3000, 20), 1.5)
    # 转化率 10 单 500 会话
    check("cvr", m.cvr(10, 500), 0.02)
    check("return_rate", m.return_rate(3, 100), 0.03)

    print("汽配词根")
    assert m.keyword_root("front brake pads for 2015 honda accord") == "front brake pads"
    print("  ✓ 年款车型被剥离")
    assert m.keyword_root("control arm fits 2012-2016 bmw 3 series") == "control arm"
    print("  ✓ 区间年款也能剥离")
    assert m.keyword_root("lower control arm") == "lower control arm"
    print("  ✓ 无年款词原样保留")
    ok += 3

    print("搜索词决策")
    d = m.decide_term("brake pads for 2015 accord", clicks=20, orders=0, spend=40)
    assert d.decision == "negative" and d.basis == "term", d
    print("  ✓ 样本够 + 高花费无单 → negative")
    d = m.decide_term("brake pads for 2016 accord", clicks=3, orders=0, spend=40, root_clicks=30)
    assert d.decision == "negative" and d.basis == "root", d
    print("  ✓ 单词不够、词根够 → 继承词根")
    d = m.decide_term("brake pads for 2017 accord", clicks=2, orders=0, spend=1, root_clicks=5)
    assert d.decision == "pool" and d.confidence == "needs_data", d
    print("  ✓ 词与词根都不够 → 进长尾池（算决策，不算未决）")
    d = m.decide_term("brake pads for 2018 accord", clicks=20, orders=1, spend=99999)
    assert d.decision == "watch" and "CPA" in d.reason, d
    print("  ✓ 有单但 CPA 超阈值 → watch 人工复核（不再无条件 keep）")
    d = m.decide_term("brake pads for 2019 accord", clicks=20, orders=10, spend=50)
    assert d.decision == "keep", d
    print("  ✓ 有单且 CPA 正常 → keep")
    ok += 5

    print("广告体检")
    e = m.evaluate_ads({"campaign": "A", "spend": "30", "sales": "0", "orders": "0", "clicks": "12"}, 0.30)
    assert e["verdict"] == "有花费无销售额", e
    print("  ✓ 有花费无销售被判出来")
    e = m.evaluate_ads({"campaign": "B", "spend": "10", "sales": "100", "orders": "5", "clicks": "40"}, 0.30)
    assert e["verdict"] == "在盈亏线内", e
    print("  ✓ ACOS 10% < 30% 盈亏线 → 在盈亏线内")
    e = m.evaluate_ads({"campaign": "C", "spend": "40", "sales": "100", "orders": "3", "clicks": "60"}, 0.30)
    assert e["verdict"] == "ACOS 高于盈亏平衡线", e
    print("  ✓ ACOS 40% > 30% → 超线")
    ok += 3

    print("销量异常排查（A8：每日销量骤涨骤跌，只按 sales_daily 相邻两个日期比）")
    rows = [
        {"date": "2026-11-01", "sku": "S1", "units": "50"},
        {"date": "2026-11-02", "sku": "S1", "units": "10"},   # 跌 80% → drop
        {"date": "2026-11-01", "sku": "S2", "units": "10"},
        {"date": "2026-11-02", "sku": "S2", "units": "30"},   # 涨 200% → spike
        {"date": "2026-11-01", "sku": "S3", "units": "20"},
        {"date": "2026-11-02", "sku": "S3", "units": "15"},   # 跌 25% → 不报
        {"date": "2026-11-01", "sku": "S4", "units": "0"},
        {"date": "2026-11-02", "sku": "S4", "units": "8"},    # 0→8 → launch（起量）
        {"date": "2026-11-02", "sku": "S5", "units": "5"},    # 只有一天 → 不报
    ]
    an = m.sales_anomalies(rows)
    by_key = {a[0]: a for a in an}
    assert "S1" in by_key and by_key["S1"][3] == "drop", an
    assert "S2" in by_key and by_key["S2"][3] == "spike", an
    assert "S4" in by_key and by_key["S4"][3] == "launch", an  # 0→有只报出单，不推断新品
    assert "S3" not in by_key and "S5" not in by_key, an
    print("  ✓ 跌超阈值报 drop、涨超阈值报 spike、0→有报 launch、小波动与单日不报")
    # 阈值可配置：把 drop 放到 90% 以下，S1 的跌 80% 就不该报
    assert not [a for a in m.sales_anomalies(rows, drop_ratio=0.90) if a[0] == "S1"]
    print("  ✓ 阈值可配（未校准值经 thresholds/sales 注入）")
    ok += 2

    print("车标硬阻断（A9：文案命中即 HOLD；适配文字不误伤）")
    for bad in ("主图含本田车标", "方向盘上有 Toyota logo", "轮毂中心盖带品牌徽标",
                "副图带 vehicle emblem 水印",
                "精美无边框车标贴纸",              # 「无边框」的「无」不是对车标的否定
                "方向盘无真皮包裹方向盘标"):        # 「无真皮」否定的是真皮，不是方向盘标
        assert m.brand_logo_hold(bad), "应命中 HOLD：%s" % bad
    print("  ✓ 车标/方向盘标/轮毂徽标/emblem/伪否定 文案命中即报 HOLD")
    for good in ("适用于 Honda Accord 2015-2018",
                 "FITS 2015-2018 Honda Accord Front Left Lower Control Arm",
                 "OE: 51360-TVA-A00",
                 "已确认无车标，背景图不含车标",
                 "场景图 no vehicle emblem、不带 logo",
                 "without brand badge 的产品图",
                 "product without any car logo design",  # 否定词带修饰语也要豁免
                 "logo free design"):                    # 否定后置也要豁免
        assert not m.brand_logo_hold(good), "不应误阻断：%s" % good
    print("  ✓ 正常适配文字与否定句（无车标/不含车标/no emblem/without any/logo free）不命中")
    ok += 2

    print("数字清洗（领星导出脏格式：货币符/千分位/百分号/会计负数）")
    for raw, want in (("$1,234.5", 1234.5), ("1,234", 1234.0), ("12.3%", 0.123),
                      ("(123)", -123.0), ("USD 45", 45.0), ("-", None), ("暂无", None)):
        got = m.num(raw)
        okflag = (got is None and want is None) or (got is not None and want is not None and abs(got - want) < 1e-9)
        assert okflag, (raw, got, want)
        print("  ✓ num(%r) = %r" % (raw, got))
    e = m.evaluate_ads({"campaign": "脏数据", "spend": "$1,500.00", "sales": "$300.00",
                        "orders": "0", "clicks": "12"}, 0.30)
    assert e["spend"] == 1500.0 and e["verdict"] == "ACOS 高于盈亏平衡线", e
    print("  ✓ $1,500/$300 不再被当成 0：判 ACOS 超线")
    ok += 8

    print("日期归一与时间窗口")
    assert m.parse_date("2026/11/4") == "2026-11-04"
    assert m.parse_date("2026年11月4日") == "2026-11-04"
    assert m.parse_date("2026-11-03 00:00:00") == "2026-11-03"
    assert m.parse_date("2026/9/1") == "2026-09-01"   # 非补零日期排序不再错乱
    assert m.parse_date("无效") is None
    rows_w = [{"date": "2026/11/1", "sku": "S1", "units": "10"},
              {"date": "2026-11-04", "sku": "S1", "units": "20"},
              {"date": "2026-11-04", "sku": "S2", "units": "5"}]
    assert len(m.latest_rows(rows_w, 1)) == 2            # 只取最新一天
    assert m.table_date_span(rows_w) == 4 and m.adjacency_gap(rows_w) == 3
    assert len(m.rows_in_month(rows_w, "2026-11")) == 3
    print("  ✓ parse_date/latest_rows/跨度/断档/按月 全部正确")
    ok += 7

    print("导入质量（MANIFEST 可读：degraded 时下游只出观察）")
    import tempfile
    tf = tempfile.NamedTemporaryFile("w", suffix=".md", delete=False)
    tf.write("- 2026-11-03 | sales_daily | 行数 9 | 缺字段 无 | ok\n")
    tf.write("- 2026-11-04 | inventory_daily | 行数 3 | 缺字段 asin,fba_available | degraded\n")
    tf.close()
    q = m.import_quality("inventory_daily", tf.name)
    assert q and q["quality"] == "degraded" and "fba_available" in q["missing"], "应读到 degraded 行"
    assert m.import_quality("sales_daily", tf.name)["quality"] == "ok", "应取每表最新一行"
    assert m.import_quality("sku_master", tf.name) is None, "没导过的表返回 None"
    os.unlink(tf.name)
    print("  ✓ MANIFEST 最新行可读：degraded/ok/未导入三态正确")
    ok += 1

    print("\n全部通过：%d 项断言" % ok)


if __name__ == "__main__":
    main()
