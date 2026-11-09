---
name: amz-sku-monthly
description: 月度看单品结构时用：只看四件事——卖什么、怎么赚、压在哪儿、广告占比。用户说「这个月 SKU 结构怎么样」时用；要完整经营复盘用 amz-week-month-review。
version: 1.0.0
author: Kelin Pan, ZCode
license: private
last_verified: 2026-11-04
review_by: 2027-02-04
platforms: [macos, linux]
metadata:
  automation:
    tags: [亚马逊, 复盘, 月度]
    related_skills: [amz-calibration, amz-ads-diagnose]
---

# 月度经营复盘

月度看结构，不看单条。单条的问题归广告诊断（`amz-ads-diagnose`）或每日简报（`amz-sku-daily`），这里只回答"这个月在往哪走"。

分层边界：当月销量/广告/库存事实 → 派生结构指标（TOP SKU 占比、广告占比、FBA 在库与滞销）→ 候选判断 → 最多三条带预期的结论（进 `judgements/`）→ 人工审批。脚本只做汇总，不算真实毛利，不把 FBA 写成全量库存。

## 用途

按月对已导入的归一化表做结构复盘，固定回答四件事：卖什么（TOP SKU 与长尾）、怎么赚（广告占比与 ACOS，但只到趋势层）、压在哪儿（FBA 在库/零库存/滞销）、下月最多三条结论。它回答"这个月结构在往哪走"，不解释单日波动，也不给出已校准的利润结论。

## 何时使用 / 不使用

**使用：**

- 每月 1 号 9:30 跑上月结构。
- 有人问"这个月怎么样"，需要先看结构再决定深挖哪条。

**不使用：**

- 不用于解释日波动——日波动归 `amz-sku-daily`。
- 不用于判断单条 campaign / 单个 Listing 怎么改——归 `amz-ads-diagnose` / `amz-listing-audit`。
- 不用于下"赚不赚钱"的利润结论——没有成本结构时只报趋势（见数据质量限制）。
- 不用于全量库存/采购/资金计划——库存段只是 FBA 可售口径。

## 最小输入

- 必需：`data/normalized/sales_daily.csv`（上月完整，字段见 `system/DATA-CONTRACT.md`）。缺它复盘做不了。
- 可选：`data/normalized/ads_daily.csv`——有才算广告花费/销售额/ACOS/占比；缺它整段跳过。
- 可选：`data/normalized/inventory_daily.csv`——有才算在库/零库存/滞销；缺它整段跳过。
- 成本结构：**当前未校准**（见下）。没有它时"怎么赚"只看广告占比趋势，不算毛利。

窗口覆盖限制见 `system/DATA-CONTRACT.md`。

## 运行与输出

```bash
# 在仓库根目录执行；用 install_skills.py 软链安装的，把 skills/ 换成 ~/.agents/skills/ 下的实际路径
python3 skills/amz-sku-monthly/scripts/run.py
```

输出四段：

1. **【卖什么】**：总销量、销售额、会话、整体转化率（`metrics.cvr`）；销售额前 5 SKU 及占比；其余 SKU 长尾合计。
2. **【怎么赚】**：广告花费、广告销售额、ACOS、广告花费占销售额比例；并固定打印"没有成本结构时算不出真实毛利，这一项只能看趋势，不能下'赚不赚钱'的结论"。
3. **【压在哪儿】**：FBA 在库 SKU 数、可售件数、可售为 0 的 SKU 数、有库存但本月 0 销的 SKU 示例；并固定标注"仅 `fba_available` 口径：在途 `fba_inbound` 与本地仓不在内"。
4. **【本月的结论去哪】**：结论写法指引（见下）。

派生指标与规则的区别：占比、ACOS、滞销计数是派生事实；"长尾要不要留""滞销要不要清"是需要人工判断的候选结论。

## 示例

```bash
# 先用合成数据验证脚本，再接上月真实归一化表
python3 scripts/selftest.py
python3 skills/amz-sku-monthly/scripts/run.py
```

对输出的任一 `<SKU>`，应能回到 `sales_daily` 对应行复算销量与销售额占比。结论（最多三条）写进：

```
judgements/<日期>-monthly.md   # 带 expected 与 review_on，格式见 system/ARCHITECTURE.md
```

## 失败降级

- 缺 `sales_daily`：输出"复盘做不了"，给导入指引，不出结构结论。
- 缺 `ads_daily`：跳过"怎么赚"段，明确披露"没有广告表"，不补写"广告正常"。
- 缺 `inventory_daily`：跳过"压在哪儿"段。
- 销售额为 0：占比分母不成立，脚本按 0 处理，不编造百分比。
- 表只覆盖部分月份：输出只代表已导入窗口，必须披露，不得写成"全月/全年"。

## 数据质量限制

- **毛利/成本未校准**：领星导出的毛利/成本是未校准参考。本技能默认不输出利润、毛利率或"赚不赚钱"的结论；要用成本结构必须先经 `amz-calibration` 对账，且来源写清。
- **库存不是全量**："压在哪儿"只用 `inventory_daily.fba_available` 的 FBA 可售口径；`fba_inbound`（在途）不算可售，本地仓/第三方仓不在默认表内，输出不得写成"全量库存"。
- 输出只覆盖已导入的归一化明细；全年 `total_sum` 不能替代每日/每月明细。
- 用销量增长不等于成功：必须同时看广告占比有没有恶化；大促、站外单、缺数造成的波动需人工剔除。

## 人工确认边界

- 脚本只汇总。改价、补货、清货、广告预算、Listing 及任何 ERP 写操作都由人批准。
- 下月结论最多三条，每条带预期与复核日；连续三个月被证实的结论才升级进 `profiles/company.md`（由 `amz-calibration` 核对，不是本脚本自动写入）。
- 涉及对外财务/利润的表述，未校准前不得对团队或客户说成事实。

## 追溯与验证

- 数据契约：`system/DATA-CONTRACT.md`（`sales_daily`/`ads_daily`/`inventory_daily` 字段）
- 公式：`skills/_shared/metrics.py`（`acos`、`cvr`、`_f`）
- 脚本：`skills/amz-sku-monthly/scripts/run.py`
- 数据覆盖限制见 `system/DATA-CONTRACT.md`
- 判断沉淀：`system/ARCHITECTURE.md`、`profiles/company.md`
- 验证：`python3 scripts/selftest.py`；四段齐全、数字可回输入行复算；结论 ≤3 条且都有预期与复核日。

## 高级规则

### Procedure

1. **卖什么**：销售额前 5 的 SKU 与占比 + 长尾合计。长尾要不要留，看退货和广告花费。
2. **怎么赚**：广告花费占销售额比例、ACOS 与盈亏线的距离。没有成本结构就只报趋势，别下"赚不赚钱"的结论。
3. **压在哪儿**：在库 SKU 数、库存合计、0 库存 SKU、有库存但本月 0 销的 SKU。
4. **下个月的三个结论**：最多三条，写进 `judgements/<日期>-monthly.md`，带预期和复核日。

### Pitfalls

- **用月报解释日波动**：月度是结构问题，日波动归每日简报。
- **把销量增长当成功**：要看广告占比有没有同步恶化。
- **没成本就下利润结论**：这是最容易犯的错，宁可只写"无法判断"。
