# 技能知识库（22 个技能的深度文档）

> 每份文档回答：这个技能干什么、数据从哪来、**逻辑链路怎么算的**、阈值为什么是这个值、输出去哪、怎么调。
> 由 `scripts/gen_skills_kb.py` 生成，深度分析在脚本里维护（改完重跑全量更新）。

| 分类 | 技能 | 一句话 |
| --- | --- | --- |
| 每日监控（自动） | [amz-inventory-alert](01-每日监控/amz-inventory-alert.md) | 库存/断货预警：按可售天数给店铺与 SKU 分档（急/关注/注意/正常），带 |
| 每日监控（自动） | [amz-stock-alert](01-每日监控/amz-stock-alert.md) | 库存紧时用：按 FBA 可售天数排队报断货风险；28 天仅为未校准运营候选预 |
| 每日监控（自动） | [amz-ads-diagnose](01-每日监控/amz-ads-diagnose.md) | 亚马逊广告诊断与复盘时用：先定目标再算盈亏线，按 CPC×转化×利润矩阵给处 |
| 每日监控（自动） | [amz-alert-center](01-每日监控/amz-alert-center.md) | 经营预警中心：按规则表扫十类风险（断货/断货风险/销售骤降/周趋势下滑/有花 |
| 每日监控（自动） | [amz-review-watch](01-每日监控/amz-review-watch.md) | 评论监控（我们自己的 ASIN）：每天看有没有新评论，重点抓 1-3 星差评 |
| 每日监控（自动） | [amz-hijack-watch](01-每日监控/amz-hijack-watch.md) | 跟卖监控（我们自己的 ASIN）：每天看卖家数有没有从 1 变多、售价有没有 |
| 报告与复盘（自动） | [amz-company-overview](02-报告复盘/amz-company-overview.md) | 管理层经营总览（一页纸 HTML）：各店铺组汇总 KPI、店铺对比、各店趋势 |
| 报告与复盘（自动） | [amz-store-daily](02-报告复盘/amz-store-daily.md) | 单店铺经营日报（HTML 图表版）：按店铺组出销售额趋势、销量、ACOS、库 |
| 报告与复盘（自动） | [amz-week-month-review](02-报告复盘/amz-week-month-review.md) | 周/月经营复盘（HTML 图表版）：本期 vs 上期环比、vs 去年同期同比 |
| 报告与复盘（自动） | [amz-profit-review](02-报告复盘/amz-profit-review.md) | 利润复盘（周报/月报）：毛利率、分店对比、亏损 ASIN 榜单、环比趋势。只 |
| 报告与复盘（自动） | [amz-sku-daily](02-报告复盘/amz-sku-daily.md) | 每天早上看店时用：昨日销量/广告/库存一段话讲完，异常单列，缺数据直说。 |
| 报告与复盘（自动） | [amz-sku-monthly](02-报告复盘/amz-sku-monthly.md) | 每月复盘时用：只看四件事——卖什么、怎么赚、压在哪儿、广告占比。 |
| 主动调研 | [amz-review-insight](03-主动调研/amz-review-insight.md) | 竞品差评分析（主动型）：拉竞品的 1-3 星评论，按「装不上/尺寸/质量/物 |
| 主动调研 | [amz-traffic-diagnose](03-主动调研/amz-traffic-diagnose.md) | 流量诊断（主动型）：某个 ASIN 的流量从哪来——核心词是哪些、前 3 词 |
| 主动调研 | [amz-product-research](03-主动调研/amz-product-research.md) | 选品调研（主动型）：判断一个类目/细分市场值不值得进——市场容量、竞争格局、 |
| 主动调研 | [amz-brand-analytics](03-主动调研/amz-brand-analytics.md) | 品牌分析（主动型）：看一个品牌在亚马逊上的盘子——有多少 ASIN 在卖、销 |
| 主动调研 | [amz-competitor-watch](03-主动调研/amz-competitor-watch.md) | 竞品与跟卖监控（卖家精灵 MCP）：盯 5–10 个同货架 ASIN 的价格 |
| 主动调研 | [amz-keyword-intel](03-主动调研/amz-keyword-intel.md) | 关键词与市场情报调研（卖家精灵 MCP）：关键词搜索量/竞争度/PPC、竞品 |
| 诊断工具 | [amz-listing-audit](04-诊断工具/amz-listing-audit.md) | 每周体检 Listing 时用：先查 OE 号与年款适配，再查标题/五点/主 |
| 诊断工具 | [amz-listing-images](04-诊断工具/amz-listing-images.md) | 做亚马逊汽配 listing 图时用：主图白底/尺寸/占比像素校验、副图检查 |
| 系统自校准（自动） | [amz-calibration](05-自校准/amz-calibration.md) | 每周日复盘时用：把到期判断拉出来对账，算技能命中率，低了就降权。 |
| 合规门禁 | [amz-compliance-tax-logistics](06-合规/amz-compliance-tax-logistics.md) | 汽配跨境合规、税务、IP、清关、HS 编码、履约与库存风险门禁。用于判断"这 |

## 脚本级监控（在 scripts/ 不在 skills/，但自动化在跑）

| 脚本 | 干什么 |
| --- | --- |
| scripts/watch_buybox.py | **购物车/跟卖全量监控**：asin.detail 批量 20 个/次，456 个 ASIN 只要 10 次调用/天（300 次/月）；直接看购物车卖家是不是我们的（config/shops.json seller_names） |
| scripts/fetch_lingxing.py | 领星拉数（店级日/月，增量缓存，每店落盘+断网重试） |
| scripts/fetch_sku.py | SKU 级拉数（sales_daily 销量明细 + inventory_daily FBA 库存快照） |
| scripts/fetch_ads.py | 广告拉数（campaign 级 + ASIN 级；ACOS 百分数归一化） |
| scripts/fetch_profit.py | 利润拉数（采购成本/毛利；52% MSKU 没录成本标 has_cost=0） |
| scripts/find_suspects.py | 销量异常筛子（免费）：库存正常但销量骤降 → 待查清单 |
| scripts/sync_base.py | 全部数据推外部表格（幂等去重；利润表只管理层可见） |
| scripts/rotate_base.py | 5 万行自动归档（主表留 90 天，老的搬归档表，先写后删） |
| scripts/push_daily_card.py | 日报卡片发群（一天一条，idempotency 防重发） |
| scripts/verify_reports.py | 报告内容验证（占位符/空表格/KPI 全 0/合规） |
| scripts/package_release.py | 打包 zip（两道闸：数据文件 + 真实 ID 脱敏） |