---
name: amz-stock-alert
description: 问「哪些 SKU 要补货/会不会断货/可售天数还剩多少」时用：按 FBA 可售天数排队报断货风险（SKU 级）。28 天是未校准的运营候选线，不判定官方低库存费；按店铺组整体看库存分档用 amz-inventory-alert（已合并、默认关闭）。
when_to_use: 问「哪些 SKU 要补货」「会不会断货」「可售天数还剩多少」时用本技能（SKU 级，合并后的唯一入口）。按店铺组整体看库存分档不要用它，那是 amz-inventory-alert（已合并、默认关闭）。
version: 1.0.0
author: Kelin Pan, ZCode
license: private
last_verified: 2026-11-04
review_by: 2027-02-04
platforms: [macos, linux]
metadata:
  automation:
    tags: [亚马逊, 库存, 断货]
    related_skills: [amz-sku-daily, amz-inventory-alert]
---

# 断货预警

## 用途

按 FBA 可售天数对输入 SKU 排序，输出急件、关注和 21–28 天候选预警清单。它回答“哪些 SKU 需要先复核补货”，不回答“具体下多少采购单”，也不判定 Amazon 低库存费资格。

分层边界：FBA 可售与销量事实 → 可售天数 → 未校准候选阈值 → 补货复核提示 → 人工结合交期、本地仓和资金决策。

## 何时使用 / 不使用

**使用：**

- 每日库存巡检，或需要确定补货复核优先级。
- 需要按同一公式对输入 SKU 做相对排序。

**不使用：**

- 不用于计算全公司库存、采购量、清货降价或资金计划。
- 不用它判断 Amazon 低库存费；官方费用需要长期约 90 天与短期约 30 天历史供货天数双口径，本脚本只有输入表的单日/窗口数据。
- 新品或无销量 SKU 没有可靠可售天数时，不硬填天数。

## 最小输入

- `inventory_daily.csv`：至少含 `asin`/`sku`、`fba_available`；`fba_inbound` 可单独披露但不得加到可售。
- `sales_daily.csv`：必须确实覆盖近 28 天；脚本把输入销量合计 ÷28 作为日均销量，不会替用户证明窗口完整。
- `config/thresholds.yaml`：`stockout` 下的 21/10/28 天均为未校准运营候选值。

字段与导入口径见 `system/DATA-CONTRACT.md`。

## 运行与输出

```bash
# 在仓库根目录执行；用 install_skills.py 软链安装的，把 skills/ 换成 ~/.agents/skills/ 下的实际路径
python3 skills/amz-stock-alert/scripts/run.py
```

输出包括：

1. 急（<10 天）、关注（<21 天）、候选预警（21–28 天）三组 SKU。
2. 每个 SKU 的 FBA 可售、输入销量和可售天数。
3. 库存口径、28 天窗口假设、候选阈值与官方低库存费的区别。

核心派生公式：`days_of_supply = fba_available / (近28天销量 / 28)`。销量为 0 时结果为 `None`，不输出伪精确天数。

## 示例

```bash
# 先用合成数据验证脚本和公式，再接入真实归一化表
python3 scripts/selftest.py
python3 skills/amz-stock-alert/scripts/run.py
```

对输出的任一 `<SKU>`，应能回到 `inventory_daily` 与 `sales_daily` 的对应行复算。预警只代表进入人工复核队列。

## 失败降级

- 缺库存表：输出数据不足，不生成补货建议。
- 缺销量表或销量为 0：不计算可售天数，仅保留库存观察。
- 输入不是完整近 28 天：结果只可作相对排序，并必须披露窗口不符。
- 阈值文件不可读：使用完整内置占位默认值并显示未校准警告；不得把默认值称为公司标准。

## 数据质量限制

- **默认输入只含 FBA 可售，不含本地仓/第三方仓**；在途也不等于可售。输出不得写成“全量库存”。
- 本地仓/在途库存是独立快照，不进入本技能的 `inventory_daily` 默认计算，不能暗中并入。
- FBA 站点视图可能重复反映同一物理库存；未经对账不得跨站点相加。
- 21/10/28 天都是候选阈值，不是公司已校准目标；自然排名与 CPC 变化仅为未校准观察。
- 官方低库存费规则以 `sources/SOURCES.md` 中 Amazon 官方链接为准，本技能不做费用资格判定。

## 人工确认边界

下单量、采购时点、交期、资金、清货降价和任何库存/ERP 写操作均由人确认。人工决策前必须补看本地仓、在途批次、供应交期和销售异常；本技能只停在预警与复核建议。含车标的内容不得借补货或 Listing 建议进入发布流程。

## 追溯与验证

- 数据与库存口径：`system/DATA-CONTRACT.md`
- 阈值来源与边界：`config/thresholds.yaml`、`config/CHANGELOG.md`
- 公式实现：`skills/_shared/metrics.py`、`skills/amz-stock-alert/scripts/run.py`
- 官方低库存费来源：`sources/SOURCES.md`
- 验证：`python3 scripts/selftest.py`、`python3 skills/_shared/test_metrics.py`；至少抽查一个 SKU 的手工复算。
