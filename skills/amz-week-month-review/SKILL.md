---
name: amz-week-month-review
description: 周会/月会前出复盘数据时用：本期 vs 上期环比、vs 去年同比、各店对比、口径注意事项（HTML 图表版）。用户说「这周/这个月怎么样」时用；只看单日看 amz-store-daily，看单月 SKU 结构用 amz-sku-monthly。
version: 1.0.0
author: Kelin Pan, ZCode
license: private
last_verified: 2026-11-04
review_by: 2027-02-04
platforms: [macos, linux]
metadata:
  automation:
    tags: [亚马逊, 周报, 月报, 同环比, 可视化]
    related_skills: [amz-store-daily, amz-company-overview]
---

# 周/月经营复盘（同环比版）

**为什么以周/月为单位**（2026-11-04 定）：单日波动噪声大（促销尾流、断货、周末效应），
日对日比对意义有限；周对周（WoW）、月对月（MoM）+ 去年同期（YoY）才是判断经营趋势的稳定口径。
日报只做「昨天有没有异常」，趋势判断看本技能的周报/月报。

## 三个比对轴（报告里必须都有）

| 轴 | 口径 | 数据要求 |
| --- | --- | --- |
| 环比 WoW/MoM | 本期 vs 紧邻上一个同长度周期 | 至少 2 个完整周期 |
| 同比 YoY | 本期 vs 去年同一日历周期 | 至少 13 个月历史（不足则明确标 `needs_data`） |
| 结构对比 | 各店铺组占比及其变化（谁在拉、谁在拖） | 同周期内各店都有数据 |

数据不足时**不估算、不外推**：缺同比就写「同比不可用（历史不足 N 个月）」。

## 用法

```bash
# 在仓库根目录执行；用 install_skills.py 软链安装的，把 skills/ 换成 ~/.agents/skills/ 下的实际路径
# 上周（自然周，周一起算）
python3 skills/amz-week-month-review/scripts/run.py --period week

# 上月
python3 skills/amz-week-month-review/scripts/run.py --period month

# 指定具体周期（ISO 周 / 年月）
python3 skills/amz-week-month-review/scripts/run.py --period week --anchor 2026-W44
python3 skills/amz-week-month-review/scripts/run.py --period month --anchor 2026-10
```

输出：`data/reports/period/<周期>_review.html`

## 报告固定结构（含必须出现的注意事项）

1. **结论条**：本期销售额 / 环比 / 同比，一句话定性（上行/平稳/下滑）。
2. **KPI 卡**：销售额、销量、ACOS、TACOS、FBA 可售——各带环比与同比箭头。
3. **趋势图**：近 12 个周期（周报按周、月报按月）销售额折线 + 本期标记。
4. **店铺贡献**：各店铺组本期销售额、占比、环比（横条 + 环形）。
5. **⚠ 本期注意事项**（固定一节，不可省）：
   - ACOS / TACOS 的绝对值含义与「成本未校准、不能当盈亏结论」的边界；
   - 可比性提示：本期是否含大促/断货/新店起量（人工填写位）；
   - 数据完整度：覆盖天数、缺哪张表、degraded 表；
   - 库存口径：仅 FBA 可售，在途与本地仓不在内。
6. **口径脚注**：数据源、币种（统一 USD）、取数时间。

## 边界

- 不展示利润/毛利（成本未校准，仓库红线）；
- 不做单 SKU 归因（归 amz-sku-daily / amz-sku-monthly 的明细层）；
- 不自动定目标（目标值缺失时同比/环比照算，达成率写 `needs_data`）。

## 何时使用 / 不使用

**用**：周会/月会前出复盘；判断"这周比上周好还是差"；需要同比看季节性。
**不用**：日度异常（用 `amz-alert-center`）、单店细看（用 `amz-store-daily`）。

## 最小输入

`shop_daily.csv` 至少覆盖 2 个完整周期（周报 14 天、月报 2 个月）；同比需 13 个月以上。
不足时**不估算**，对应栏写「不可用」。

## 失败降级：可比性护栏（最容易被误读的机制）

| 情况 | 行为 |
| --- | --- |
| 本期覆盖 < 70% 日历天数 | 结论条直接写「数据仅覆盖 N/M 天，不建议与上期比」 |
| 上期覆盖 < 70% | **不出环比数字**，写「上期不完整，环比较失真不展示」 |
| 去年同期 < 70% | 同比写「不可用（去年同期仅覆盖 N 天）」 |
| 完全没有本期数据 | 退出码 **2** |

> 为什么这么严：9 月只有 11 天数据时，机器会算出「+214% 增长」这种假信号。
> 宁可说"不可比"，也不给一个看起来像真的百分比。

## 人工确认边界

- 本期是否含大促/断货/新店起量——**报告留了人工填写位，机器不猜**；
- 同比/环比只描述变化，不解释原因；原因归因走 `amz-ads-diagnose` 或人工复盘。
