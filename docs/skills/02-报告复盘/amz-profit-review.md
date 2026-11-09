# amz-profit-review

> 利润复盘（周报/月报）：毛利率、分店对比、亏损 ASIN 榜单、环比趋势。只算录了采购成本的 ASIN，不含头程——口径会写在报告里。

| | |
| --- | --- |
| 类型 | 报告与复盘（自动） |
| 运行 | 周一 08:30 / 每月 3 号 09:30（先 fetch_profit.py） |
| 有脚本 | 是 |

## 数据源

profit_daily（领星 query_order_profit_list）；关键字段 avg_purchase_costs（单件采购价）/ gross_profit / gross_margin

## 逻辑链路（这是怎么算出来的）

① 只取 has_cost=1 的行——没录采购成本的不能算（把『没录』当『成本 0』毛利率虚高 8 个点：实测 29.9% vs 21.5%）

② 按 (店,ASIN) 合并日行——不合并同一 ASIN 月榜出现多次（实测 23 条→16 个）

③ 店级+总体毛利率，环比变化

④ 亏损明细全部列出按店分组：销售额 0 却亏损的标『无销售』（退货/仓储费，跟卖亏是两回事）

⑤ 口径红线写在报告里：领星已扣采购+FBA配送+佣金，但头程恒为 0——毛利率是上限值

## 为什么这样设计 / 阈值依据

领星字段名的坑：gross_profit 不是毛利，是扣完采购+配送+佣金的数；total_costs 只等于采购成本。实测 10 月：毛利率 29.9%，16 个 ASIN 亏损，shop_b 占 9 个。

## 输出去向

data/reports/profit/ → 云盘；只有管理层能看（外部表格利润表也是）

## 怎么调

config/targets.json profit 段（target 0.30 / floor 0.15 / critical 0.0）

---

本文档由 `scripts/gen_skills_kb.py` 生成；深度分析改脚本里的 KB 数据，描述/用法看 `skills/amz-profit-review/SKILL.md`。