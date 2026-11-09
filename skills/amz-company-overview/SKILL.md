---
name: amz-company-overview
description: 老板/管理层问「多店整体怎么样」时用：一页纸 HTML 总览，汇总 KPI、店铺对比、各店趋势与异常摘要，不含 SKU 明细。要单店细节用 amz-store-daily，要预警清单用 amz-alert-center。
version: 1.0.0
author: Kelin Pan, ZCode
license: private
last_verified: 2026-11-04
review_by: 2027-02-04
platforms: [macos, linux]
metadata:
  automation:
    tags: [亚马逊, 管理层, 总览, 可视化]
    related_skills: [amz-store-daily, amz-sku-daily]
---

# 管理层经营总览（一页纸）

给老板/管理层的各店铺组汇总视图，遵守「5 秒看懂」：
结论条（红黄绿）→ 汇总 KPI → 店铺销售额对比与占比 → 各店近 30 天趋势 → 异常摘要。
**不放 SKU 级明细**（细节看 amz-store-daily 的单店报告）。

## 数据来源与口径

- `data/normalized/shop_daily.csv`（由 `scripts/fetch_lingxing.py` 定时拉取）；
- USD、下单口径、跨店铺组相加（已统一币种，允许加总）；
- 红线继承：不展示利润/毛利；库存仅 FBA 可售口径。

## 用法

```bash
# 在仓库根目录执行；用 install_skills.py 软链安装的，把 skills/ 换成 ~/.agents/skills/ 下的实际路径
python3 skills/amz-company-overview/scripts/run.py
# 归档：--kind daily --title "多店总览"
```

## 输出

- `data/reports/mgmt/<日期>_overview.html`
- 结构：结论条 → 全公司 KPI 卡（销售额/销量/TACOS/FBA可售，带环比）→
  多店对比横条 + 占比环形 → 各店趋势（小图并排）→ 异常摘要（环比骤变/断档）

## 不做什么

- 不做 SKU/ASIN 分析；不做广告诊断（归 amz-ads-diagnose）；不改任何业务数据。

## 何时使用 / 不使用

**用**：老板每天早上 5 秒看全公司；周会开场前对齐大盘；发现某店异常后转去看单店日报。
**不用**：需要 SKU 明细（用 `amz-store-daily` / `amz-sku-daily`）、需要同环比趋势
（用 `amz-week-month-review`）。

## 最小输入

`data/normalized/shop_daily.csv`（`scripts/fetch_lingxing.py` 产出）+ `config/shops.json`。
两样都没有就跑不起来——本技能**不猜数**。

## 失败降级

| 情况 | 行为 |
| --- | --- |
| 无 `shop_daily` | 退出码 **2**，提示先拉数 |
| 各店日期不同步 | 各取各自最近完整日，页眉标注"数据截至 X" |
| 某店完全没有数据 | 该店从对比图与占比图里缺席，异常摘要里不出现（不补 0） |

## 人工确认边界

- 一页纸只做"看到什么"，**异常原因与处置由人判断**；
- 「销售额环比跌 20%」这类阈值判定是占位值，别当 KPI 考核线；
- 不放 SKU 明细，避免管理层被单条商品带偏。
