---
name: amz-review-insight
description: 用户要从竞品客诉里找选品/改款机会时才用（需卖家精灵）：拉竞品 1–3 星评论，按装不上/尺寸/质量/物流/描述不符/价格归类，每类给出「你能怎么用」。只看自己的差评用 amz-review-watch。
version: 1.0.0
author: Kelin Pan
license: private
last_verified: 2026-11-04
review_by: 2027-05-04
platforms: [macos, linux]
metadata:
  automation:
    tags: [亚马逊, 竞品, 差评, 选品]
    related_skills: [amz-review-watch, amz-product-research]
---

# 竞品差评分析

**自己的差评只能改自己；竞品的差评是免费的选品调研。**

一个 200 条评论里 40 条说「装不上」的品 → 它的 fitment 数据烂 →
你做一个「装得上同款」就能直接吃它的客诉流量。


## 交互协议（主动调用时：先问清，再执行）

本技能是**主动式**技能。被调用时不要直接闷头跑脚本：先核对下面的前置信息，
缺哪项就**用带选项的问题**一次问清（一次最多 3 个问题，能合并就合并），拿到答案再执行。

| 前置信息 | 为什么需要 | 选项 / 默认值 |
|---|---|---|
| ASIN / SKU 清单 | 评论分析对象 | 必填或选「本店重点 SKU」 |
| 时间窗与星级 | 差评还是全量 | 默认近 90 天 + 1–3 星差评优先 |

多轮对话规则：
1. 用户后续补充或修改口径时，以**最新一轮**为准，并复述确认关键参数（范围/对象/阈值）。
2. 信息齐全后先用一句话复述「我要用什么对象 + 什么时间窗 + 什么阈值 + 输出什么」，再动手。
3. 缺数据/缺密钥时直说并给替代路径，**不编数**；外部写操作（发消息、写外部表格、改广告）必须显式确认。
4. 用户只想快速要结果时，可直接采用上表默认值，但要在开头列出所用默认值。

---


## 用途

给几个竞品 ASIN，拉它们的 1-3 星评论，按问题类型归类，每类告诉你：
- 多少条、占差评的百分比
- 代表评论原文
- **你能怎么用**（选品方向 / 改款点 / 差异化卖点）

## 何时使用 / 不使用

**使用：**
- 想进某个类目前，先看头部品的差评在哪
- 自己的品卖不动，想知道竞品是靠什么活下来的
- 改款前，找「大家都没做好」的点

**不使用：**
- 看自己产品的差评 → `amz-review-watch`（那是每天自动跑的）
- 想看评论里的情感倾向 → 用卖家精灵官方「评论痛点分析助手」

## 怎么跑

```bash
# 在仓库根目录执行；用 install_skills.py 软链安装的，把 skills/ 换成 ~/.agents/skills/ 下的实际路径
# 拉并分析（每个 ASIN 花 1 次额度，最多 100 条评论）
python3 skills/amz-review-insight/scripts/run.py --asins B0D62SYW8S,B0GJRVBQT2 --fetch

# 用已存快照重跑（不花额度）
python3 skills/amz-review-insight/scripts/run.py --asins B0D62SYW8S

# 群消息摘要
python3 skills/amz-review-insight/scripts/run.py --asins B0D62SYW8S --format text
```

竞品 ASIN 从哪来：`profiles/competitors.md`（那份名单本来是给 `amz-competitor-watch` 用的，这里可以直接复用）。

## 七个问题类型（关键词归类，不依赖大模型）

| 类型 | 命中词示例 | 你能怎么用 |
| --- | --- | --- |
| **装不上/适配错** | doesn't fit / wrong part / not compatible | 做同款把适配车型年份写全 + 装配图，直接吃客诉流量 |
| 尺寸/规格不对 | too big / size / mm / inch | 关键尺寸标在图上，带单位换算 |
| 质量问题 | broke / cracked / cheap / flimsy | 查具体哪里坏，做同款时在那处加成本 |
| 物流/包装 | arrived / damaged / missing | 改进包装，拿「开箱完整」当卖点 |
| 描述不符 | not as described / misleading | 描述保守、图片实拍，退货率会低 |
| 价格/性价比 | overpriced / not worth | 这价位有空间，看它采购成本能不能压 |
| 安装困难 | hard to install / no instruction | 配图文说明书或短视频，差异化点 |

## 口径与边界（读结论前必须知道）

1. **归类靠关键词匹配**（英文），中文评论和反讽会归错——抽样读几条确认
2. **评论是卖家精灵采集的，不是亚马逊全量**，比例是「样本内占比」不是总体
3. 用**标准版**接口（最多 100 条）。`asin.review.list.extended` 能拉 500 条但要 2 分钟、额度高，看竞品不值得
4. 「你能怎么用」是**方向建议**，不是自动改 Listing——写文案仍要人工

## 成本

每个 ASIN 1 次卖家精灵调用。看 5 个竞品 = 5 次。**别拿它当爬虫天天跑。**

## 变更记录

- **2026-11-04 新建**：参考 nexscope `amazon-review-analyzer`、
  liangdabiao 的 sorftime 差评分析、APIClaw `review insights` 的做法，
  共同点都是「按问题类型归类」而不是简单列评论。
