---
name: amz-store-daily
description: 每天早上看单个店铺经营状况时用：出一份单店 HTML 日报（销售额趋势、销量、ACOS、库存卡）。用户问「昨天怎么样/这个店怎么样」时用；要全公司多店对比用 amz-company-overview，要 SKU 级明细用 amz-sku-daily。
version: 1.0.0
author: Kelin Pan, ZCode
license: private
last_verified: 2026-11-04
review_by: 2027-02-04
platforms: [macos, linux]
metadata:
  automation:
    tags: [亚马逊, 日报, 店铺, 可视化]
    related_skills: [amz-sku-daily, amz-company-overview]
---

# 单店铺经营日报（HTML 图表版）

给每个店铺组（shop_a / shop_b / shop_c，见 `config/shops.json`）出一份**单文件 HTML 图表日报**：
KPI 卡片带环比、近 30 天销售趋势、销量柱、ACOS×花费双轴、库存卡片。零 JS（SVG 直出），
云文档预览/断网/下载打开都有图。

## 数据来源与口径（先读这个）

- 唯一数据源：`data/normalized/shop_daily.csv`（由 `scripts/fetch_lingxing.py` 从领星 MCP 定时拉取；
  列定义见 `system/DATA-CONTRACT.md` 的 shop_daily 段）。
- 口径：领星「产品表现 total_sum」，**USD、下单口径**，单店组多站点合并；
- 红线继承：毛利/利润字段未校准，本报告**不展示任何利润数字**；最新一天若是今天，数据
  尚未在领星齐产，报告自动回退到最近一个「非今天」的完整日并明确标注。

## 用法

```bash
# 在仓库根目录执行；用 install_skills.py 软链安装的，把 skills/ 换成 ~/.agents/skills/ 下的实际路径
# 数据先到位（Mac Mini 定时任务里跑；或手工）
python3 scripts/fetch_lingxing.py --days 7

# 出全部店铺组的日报
python3 skills/amz-store-daily/scripts/run.py

# 只出一家
python3 skills/amz-store-daily/scripts/run.py --shop shop_a
## 输出

- 文件：`data/reports/shop/<店铺组>/<日期>_<店铺组>.html`（单文件，可直发）
- stdout：一行摘要（供定时任务通知用）
- 结构：结论条 → KPI 卡片（销售额/销量/ACOS/转化/FBA可售，带环比红绿）→
  近 30 天销售额趋势 → 销量柱 → ACOS 与广告花费 → 近 7 日明细表

## 不做什么

- 不碰 ASIN 级明细（那是 amz-sku-daily 的活）；
- 不做跨店铺对比（那是 amz-company-overview 的活）；
- 不展示利润/毛利（未校准红线）。

## 何时使用 / 不使用

**用**：每天上班第一件事看自己店；老板问"昨天怎么样"；发现异常要定位到某一天。
**不用**：跨店对比（用 `amz-company-overview`）、周月趋势（用 `amz-week-month-review`）、
SKU 级归因（用 `amz-sku-daily`）。

## 失败降级

| 情况 | 行为 |
| --- | --- |
| 没有 `shop_daily` 数据 | 打印提示并以退出码 **2** 结束，不生成空报告 |
| 只有今天的数据 | 退而用今天（页眉标注"数据未齐"），不假装是完整日 |
| 某店某天缺行 | 该点在趋势图上断开（不画 0），KPI 卡按该店最新可用日计算 |
| 店铺组名写错 | 列出可选组名并退出码 **2** |

## 人工确认边界

- 报告只陈述事实与环比，**不给"该补货/该调价"的结论**（那是预警中心与人的活）；
- 成本未校准 → 报告里没有任何利润数字，也不允许运营拿 ACOS 当盈亏线用。
