---
name: amz-inventory-alert
description: 仅当要按店铺组整体看库存分档、且已有 shop_daily 时用：出急/关注/注意/正常分档与补货建议。默认关闭——问「哪些 SKU 要补货」一律用 amz-stock-alert，不要用本技能。
when_to_use: 只有明确要「按店铺组整体」看库存分档、且已有 shop_daily 时用；问「哪些 SKU 该补货」「会不会断货」时不要用本技能，改用 amz-stock-alert（SKU 级可售天数 + 补货复核）。
version: 1.0.0
author: Kelin Pan, ZCode
license: private
last_verified: 2026-11-04
review_by: 2027-02-04
platforms: [macos, linux]
metadata:
  automation:
    tags: [亚马逊, 库存, 断货, 预警, 补货, 已合并]
    related_skills: [amz-stock-alert, amz-alert-center, amz-store-daily]
---

# 库存与断货预警（店级口径 · 已合并）

> **2026-11-04 起与 `amz-stock-alert` 合并，单入口只留 SKU 级可售天数版**（见 CHANGELOG、
> `config/automations.yaml` 的 `inventory-alert` 已 `default: off`）。保留本技能只为一件事：
> 按**店铺组整体**看库存分档。问「哪个 SKU 要补货」一律走 `amz-stock-alert`。
> 两套口径的阈值都来自 `config/thresholds.yaml`，不要在本文件里改数字。

**为什么库存要单独盯**：断货是唯一「不可逆」的伤害——排名掉下去要 6–8 周才恢复，
而改价、改 Listing 都能改回来。所以库存要单独盯、单独推、盯得比别人勤。

## 两套口径（先看清用的是哪个）

| 口径 | 数据源 | 粒度 | 什么时候有 |
| --- | --- | --- | --- |
| **店级**（默认） | `shop_daily.fba_available` + 近 N 天销量 | 店铺组 | 每天自动有（MCP 拉数） |
| **SKU 级**（可选） | `inventory_daily.fba_available` + `sales_daily` | SKU/ASIN | 手工导 `inventory_daily` 才有 |

**报告里必须标清是哪套**——店级说"这家店整体还能卖 X 天"，SKU 级才说"这个件还能卖 X 天"。
两套都缺时明确报 `needs_data`，不拿"没有报警"冒充"库存健康"。

## 分档（阈值在 config/thresholds.yaml 的 stockout 段）

| 档 | 可售天数 | 动作 |
| --- | --- | --- |
| **急** | < 7 天 | 当天处理：紧急补货 / 转 FBM / 停广告止损 |
| **关注** | 7–14 天 | 核对在途与本地仓，走补货流程 |
| **注意** | 14–21 天 | 排进本周补货计划 |
| 正常 | ≥ 21 天 | 不动 |

⚠️ **可售天数只算 FBA 可售**：在途、本地仓、海外仓都不在表里。所以"3 天"可能实际是"3 天 + 在途 20 天"，
报告会把在途单列（有的话）并提示人工核对。

## 用法

```bash
# 在仓库根目录执行；用 install_skills.py 软链安装的，把 skills/ 换成 ~/.agents/skills/ 下的实际路径
python3 skills/amz-inventory-alert/scripts/run.py                 # 全部店铺组
python3 skills/amz-inventory-alert/scripts/run.py --shop shop_a     # 单店
python3 skills/amz-inventory-alert/scripts/run.py --format text    # 群消息摘要
python3 skills/amz-inventory-alert/scripts/run.py --days 7         # 用近 7 天算日均（默认）
```

输出：`data/reports/inventory/<日期>_inventory.html`
退出码：**有"急"或"关注"档 → 1**（定时任务据此叫人）；数据缺失 → 2；全部正常 → 0。

## 报告结构

1. **结论条**：N 个急 / M 个关注 / K 个注意（红黄绿）
2. **KPI 卡**：全公司 FBA 可售件数、加权可售天数、急件数、目标达成（vs `config/targets.json`）
3. **店铺分档横条图**：各店可售天数，阈值线标注
4. **明细表**：店铺/SKU | 可售件数 | 日均销量 | 可售天数 | 在途 | 档位 | 建议
5. **⚠ 注意事项**：FBA 口径限制、在途未计入、补货提前期需要人工确认、断货对排名的伤害

## 何时使用 / 不使用

**用**：每天早晚各扫一次；大促前专项检查；某个 SKU 突然起量后确认库存够不够。
**不用**：判断该补多少货（交期与起订量要人工定）；判断库存资金占用（成本未校准）。

## 失败降级

| 情况 | 行为 |
| --- | --- |
| 无 `shop_daily` | 退出码 2，提示先拉数 |
| 无销量数据 | 只报库存绝对值，不算天数（不除零） |
| 可售为 0 但近 N 天 0 销 | 标"零库存零动销"（可能是停售品，不当断货急件） |
| 在途字段缺失 | 报告注明"在途不可见，实际可售可能更多" |

## 人工确认边界

- 补货量、交期、起订量 **一律人工定**——本技能只回答"还能卖几天、急不急"；
- 不创建 FBA 入库单、不改库存、不调价格；
- 断货阈值用 `thresholds.yaml` 的 `stockout` 段（占位值），校准要等有真实补货提前期数据。
