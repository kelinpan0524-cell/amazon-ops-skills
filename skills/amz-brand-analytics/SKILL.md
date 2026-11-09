---
name: amz-brand-analytics
description: 用户要评估一个品牌、或盯对手品牌整体动向时才用（需卖家精灵）：该品牌在售 ASIN 数、销量分布、类目份额、新品起势。看单个 ASIN 用 amz-traffic-diagnose。
version: 1.0.0
author: Kelin Pan
license: private
last_verified: 2026-11-04
review_by: 2027-05-04
platforms: [macos, linux]
metadata:
  automation:
    tags: [亚马逊, 品牌, 竞品, 份额]
    related_skills: [amz-product-research, amz-competitor-watch]
---

# 品牌分析

**看品牌整体，不是单个 ASIN。** 单个 ASIN 监控用 `amz-competitor-watch`。

## 两个方向

### 方向 A：看自己的品牌
- 我们在这个类目里占多少份额
- 哪些 ASIN 是主力、哪些在拖后腿
- 新品（半年内上架）起没起来

### 方向 B：看竞争对手的品牌
- 对方一共多少 ASIN 在卖
- 是靠一个爆款还是多个款撑着
- 最近有没有上新（上新节奏 = 他们的选品方向）

## 流程

### 第 1 步：拉品牌下的 ASIN
```
asin.list(marketplace="US", brandInclude=["BRAND_NAME"], page={"cursor":0,"size":100})
```
拿到：ASIN、标题、价格、评分、月销量、月销售额、BSR、变体数、上架时间。

**品牌名要写亚马逊上的写法**，不是中文名。不确定就先 `asin.detail` 查一个已知 ASIN 拿 `brand` 字段。

### 第 2 步：销量分布（靠一个爆款还是多个款）
```
asin.sales.trend(asin="主力 ASIN", metrics=["parentSales"])
```
或者直接对 `asin.list` 返回的 `monthlySales` 排序：
- **Top1 ASIN 占品牌销量 >50%** → 单点依赖，那个款被跟卖/断货就崩
- Top5 占 80% 左右 → 健康

### 第 3 步：类目份额
```
category.top.list(categoryId="路径", dimension="brand", topN=20)
```
看这个品牌在类目里排第几、占多少。**如果不在 Top20 里，说明它的盘子主要在别的类目**。

### 第 4 步：新品节奏（对手在上什么）
按 `availableDate` 排序，看最近 6 个月上架的 ASIN：
- 上新频率高 → 在铺货试款
- 上新少但单品销量高 → 在打磨精品

## 输出什么

| 指标 | 怎么算 | 说明 |
| --- | --- | --- |
| ASIN 数 | `asin.list` 返回条数 | 在卖的总数 |
| 月销售额合计 | 各 ASIN `monthlyRevenue` 相加 | 品牌盘子 |
| Top1 集中度 | Top1 销量 / 总销量 | >50% = 单点依赖 |
| 新品占比 | 半年内上架 ASIN 的销量 / 总销量 | 看品牌是否在迭代 |
| 类目排名 | `category.top.list` 里第几 | 不在 Top20 = 主战场不在这 |

## 跟我们自己的数据对照（这个组合最有价值）

```
品牌分析（卖家精灵，看市场）
  ↓
对比我们的店铺数据（领星，看自己）
  ↓
结论：我们在类目里占多少、差距在哪
```

比如：某竞品品牌月销 $800K、Top1 ASIN 占 60%、半年上新 12 个；
我们三个店月销合计 $300K（约 $42K）、8 个 ASIN、半年上新 2 个
→ 差距不是产品，是**上新节奏和 SKU 密度**。

## 口径与边界

1. 销量/销售额都是**卖家精灵估算**，亚马逊不公布真实销量，只能做相对判断
2. 品牌名匹配是**精确匹配**（大小写不敏感），缩写/子品牌要单独查
3. 多店铺卖家可能有多个品牌名，要分别查再相加
4. **不查品牌备案/侵权风险**——那是 `amz-compliance-tax-logistics` 的事

## 成本

每个品牌约 2-5 次调用（`asin.list` 翻页 + 类目 Top）。**按次计费**，看 3 个竞品品牌约 15 次。

## 变更记录

- **2026-11-04 新建**：参考 nexscope `amazon-brand-analytics`、APIClaw `competitor deep teardown`。
  关键指标是 **Top1 集中度** 和 **新品占比**——这两个看的是品牌的健康度和迭代速度，
  比"总销量多少"更能判断它会不会掉下来。
