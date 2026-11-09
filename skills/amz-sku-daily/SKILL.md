---
name: amz-sku-daily
description: 每天看单品明细时用：一段话讲完昨日销量/广告/库存，异常单列，附 SKU 与 ASIN 级可排序表格。用户问「哪些 SKU 出问题/单品卖得怎么样」时用；只看店铺汇总用 amz-store-daily。
version: 1.0.0
author: Kelin Pan, ZCode
license: private
last_verified: 2026-11-04
review_by: 2027-02-04
platforms: [macos, linux]
metadata:
  automation:
    tags: [亚马逊, 每日, 简报]
    related_skills: [amz-stock-alert, amz-ads-diagnose]
---

# 每日经营简报

## 用途

把昨天的销售、广告和 FBA 库存事实汇总成“概览 / 异常 / 待确认 / 数据情况”四段，并标出需要进一步诊断的 SKU 或 campaign。它回答“昨天发生了什么”，不直接回答“为什么发生、应该改什么”。

分层边界：归一化事实 → 汇总与相邻数据日期变化 → 未校准候选规则 → 异常提示 → 人工诊断。

## 何时使用 / 不使用

**使用：**

- 每日看店或有人问“昨天怎么样”。
- 需要先筛出销量骤变、广告无销售花费、低库存等异常，再决定深挖顺序。

**不使用：**

- 不用它直接改竞价、预算、价格、Listing 或库存。
- 不用单日波动推断差评、竞品、大促等原因；异常只表示需要复核。
- 需要盈亏、毛利或全量库存结论时，改走有完整成本与仓库数据的专业流程。

## 最小输入

`data/normalized/` 中按任务需要准备：

- 必需：`sales_daily.csv`；缺它只能报告数据不足。
- 可选：`ads_daily.csv`、`inventory_daily.csv`；缺哪张就只省略对应事实并明确披露，不能补写“正常”。
- 规则：`config/thresholds.yaml`。销量异常使用相邻两个**有数据的日期**，不保证是自然日连续两天。

导入与字段见 `system/DATA-CONTRACT.md`。

## 运行与输出

```bash
# 在仓库根目录执行；用 install_skills.py 软链安装的，把 skills/ 换成 ~/.agents/skills/ 下的实际路径
python3 skills/amz-sku-daily/scripts/run.py
```

输出固定为四段：

1. **概览**：输入表中的销量、销售额、广告等原始事实及汇总。
2. **异常**：按候选阈值筛出的对象和方向，不改写脚本数字。
3. **待确认**：需要归因或人工判断的事项。
4. **数据情况**：实际覆盖的表、缺口和降级状态。

## 示例

```bash
# 在仓库根目录执行；没有真实数据时先跑合成数据自测
python3 scripts/selftest.py
python3 skills/amz-sku-daily/scripts/run.py
```

正常结果应能定位到具体 `<SKU>` 或 `<campaign>`。出现“零销量后出单”只表示前后两个数据日期由 0 变为有销量，不表示识别出新品。

## 失败降级

- 缺表或空表：输出 `needs_data`/数据缺口，不生成经营结论。
- 只有一个数据日期：不计算骤涨骤跌。
- 某 SKU 在相邻日期没有记录：不把缺失行当 0，也不推断销量归零。
- 脚本失败：先运行 `python3 scripts/selftest.py` 与 `python3 skills/_shared/test_thresholds.py` 定位数据或阈值问题。

## 数据质量限制

- 输出只覆盖已导入的归一化明细；全年 `total_sum` 不能替代每日明细。
- **毛利和成本尚未校准**：本技能不输出利润、毛利率或盈亏平衡结论。
- 库存段仅使用 `inventory_daily.fba_available` 的 FBA 可售口径；在途不是可售，本地仓/第三方仓不在默认表内，不能称为全量库存。
- 候选阈值不是公司校准目标；大促、站外单和缺数造成的波动需要人工剔除或解释。

## 人工确认边界

脚本只生成简报和异常提示。广告、价格、Listing、补货、对外消息及任何 ERP 写操作都必须另行诊断并由人批准；本技能不自动执行外部动作。含车标的文案或图片不得发布，必须移除/替换并复核；正常车型适配文字不因该规则自动阻断。

## 追溯与验证

- 数据契约：`system/DATA-CONTRACT.md`
- 阈值及来源/边界：`config/thresholds.yaml`
- 公式与异常逻辑：`skills/_shared/metrics.py`
- 任务映射见`docs/WORKFLOWS.md`
- 验证：`python3 scripts/selftest.py`；数字应能抽查回输入行，异常应能定位到具体对象。
