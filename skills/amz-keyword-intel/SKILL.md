---
name: amz-keyword-intel
description: 用户要选词、看关键词市场时才用（需卖家精灵）：搜索量、竞争度、PPC、竞品 ASIN 与类目趋势，出结构化调研。看自己 ASIN 的流量结构用 amz-traffic-diagnose。
version: 1.0.0
author: Kelin Pan, ZCode
license: private
last_verified: 2026-11-04
review_by: 2027-02-04
platforms: [macos, linux]
metadata:
  automation:
    tags: [亚马逊, 关键词, 选品, 卖家精灵, 市场情报]
    related_skills: [amz-ads-diagnose, amz-listing-audit]
---

# 关键词与市场情报调研（卖家精灵 MCP）

**定位**：领星看「自己的店铺」（经营数据），卖家精灵看「外面的市场」（搜索量/竞品/类目）。
本技能回答「这个词/这个类目/这个竞品值不值得做」，不回答「我店卖得怎样」。


## 交互协议（主动调用时：先问清，再执行）

本技能是**主动式**技能。被调用时不要直接闷头跑脚本：先核对下面的前置信息，
缺哪项就**用带选项的问题**一次问清（一次最多 3 个问题，能合并就合并），拿到答案再执行。

| 前置信息 | 为什么需要 | 选项 / 默认值 |
|---|---|---|
| ASIN 或关键词 | 研究对象 | 必填其一；都没有则先问 |
| 目的 | 选词/反查竞品/监控排名 | 选项：反查竞品词（默认）/ 扩词 / 排名监控 |

多轮对话规则：
1. 用户后续补充或修改口径时，以**最新一轮**为准，并复述确认关键参数（范围/对象/阈值）。
2. 信息齐全后先用一句话复述「我要用什么对象 + 什么时间窗 + 什么阈值 + 输出什么」，再动手。
3. 缺数据/缺密钥时直说并给替代路径，**不编数**；外部写操作（发消息、写外部表格、改广告）必须显式确认。
4. 用户只想快速要结果时，可直接采用上表默认值，但要在开头列出所用默认值。

---


## 前置条件

ZCode/客户端已配置卖家精灵 MCP（`https://mcp.sellersprite.com/v2/mcp`，header `secret-key`；
见 `docs/DATA-SOURCES.md`）。**额度按次计费**，纪律见下。

## 调用纪律（省额度三规则）

1. **默认 size=10**：所有列表查询用小分页，看清结构再决定要不要翻页；
2. **先批量快照后趋势**：先用 `keyword.batch.info`（一次最多 20 词的当月快照）筛出值得深入的词，
   再对入选词用 `keyword.trend` / `keyword.aba.trend` 拉月度序列——不要对 20 个词全拉趋势；
3. **品找词优先于词找词**：已知目标 ASIN 时用 `keyword.asin.list`（该 ASIN 的流量词+占比），
   比凭空猜种子词更省。

## 常用工具对照

| 要什么 | 工具 | 要点 |
| --- | --- | --- |
| 一批词的当月搜索量/PPC/竞争度 | keyword.batch.info | ≤20 词/次；searchVolume/purchaseRate/bid/products |
| 一个词的 36 个月趋势 | keyword.trend | 只给入选词用 |
| 某词的 ABA 排名与 Top3 点击份额 | keyword.aba.list / keyword.aba.trend | 判断垄断度（monopolyClickRate>0.3 慎入） |
| 某 ASIN 的流量词与出单词 | keyword.asin.list | 品找词主路径；trafficShare 排序 |
| 竞品 ASIN 详情/销量趋势 | asin.detail / asin.sales.trend / asin.prediction.sales | 竞品调研 |
| 类目市场结构 | category.report.detail（需先 category.search 拿完整路径） | 选品 |

## 输出合同（调研报告固定结构）

```
【结论】值不值得做：一句话 + 三档（进入/观察/放弃）
【关键词表】词 | 月搜索量 | 购买率 | PPC参考 | 竞品数 | 供需比 | 判断(keep/watch/negative/pool)
【趋势】入选词的月度搜索量方向（升/平/降，注明窗口）
【垄断度】Top3 点击份额；>30% 标红
【竞品】3-5 个对标 ASIN：价格/评分/评论数/月估销
【汽配特有】词根继承检查（年款+品牌+车型剥离，调 skills/_shared/metrics.keyword_root）；
            fitment 长尾词单列（含 YMM 的词）
【口径脚注】数据源=卖家精灵（估算值，非官方）· 读取日期 · 额度消耗 N 次
```

## 边界

- 卖家精灵的销量/搜索量是**估算值**，报告里必须带"估算"标注，不得与领星实绩混写；
- 不用调研结论直接改 Listing/广告（那是 amz-ads-diagnose + 人工审批的事）；
- 敏感词（车标/品牌词）调研照走 A9 硬阻断规则。

## 何时使用 / 不使用

**用**：评估一个词/类目值不值得投；竞品为什么起量；给新品挑种子词。
**不用**：看自己店卖得怎样（用 `amz-store-daily` / `amz-sku-daily`）；日常广告调优
（用 `amz-ads-diagnose`，那里有真实花费与订单）。

## 失败降级

| 情况 | 行为 |
| --- | --- |
| 未配 `SELLERSPRITE_MCP_KEY` | 明确报"缺卖家精灵凭证"，不给任何估算数字 |
| 词库未收录该词 | 明确写"未收录"（不是"搜索量为 0"） |
| 额度用尽 | 停手并报告已消耗次数，不重试轰炸 |
| 类目路径不完整 | 先 `category.search` 拿完整 nodeIdPath，不拿短 ID 硬查（会静默查空） |

## 人工确认边界

- 卖家精灵是**估算数据**（搜索量/销量/BSR 都是模型推算），只能做相对判断，不能当财务口径；
- 调研结论不直接改 Listing/广告——改是 `amz-ads-diagnose` 出建议 + 人批准；
- 汽配词要过词根继承与 fitment 检查（`metrics.keyword_root`），别只看总搜索量。
