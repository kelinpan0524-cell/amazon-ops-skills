---
name: amz-hijack-watch
description: 用户问「有没有被跟卖/购物车还在不在」时才用（我们自己的 ASIN）：每天看卖家数是否从 1 变多、售价是否被压低，只报变化不抓页面。盯别人的 ASIN 用 amz-competitor-watch。
version: 1.0.0
author: Kelin Pan
license: private
last_verified: 2026-11-04
review_by: 2027-05-04
platforms: [macos, linux]
metadata:
  automation:
    tags: [亚马逊, 跟卖, 购物车]
    related_skills: [amz-competitor-watch, amz-listing-audit]
---

# 跟卖监控

盯**我们自己的** ASIN：卖家数有没有从 1 变多、售价有没有被压低。

和 `amz-competitor-watch` 的分工：
- 那个盯**别人**的 ASIN，回答"同行在干什么"（每周一次就够）；
- 这个盯**自己**的 ASIN，回答"我们的购物车还在不在手里"（要每天看，因为跟卖进来当天就开始抢单）。

## 用途

对月销额前 10–20 的自家 ASIN 每天拉一次快照，只比对"卖家数"和"售价"两项相对变化：

| 信号 | 判什么 | 级别 | 先做什么 |
| --- | --- | --- | --- |
| 卖家数 1 → ≥2 | 有人跟卖了 | **critical** | 去后台确认 FBA/FBM 跟卖；看对方价格与配送 |
| 卖家数继续增加 | 跟卖在扩散 | high | 看新增卖家价格，算要不要跟价 |
| 卖家数回到 1 | 跟卖退出了 | info | 不用动，记一笔 |
| 有跟卖 + 售价跌 >5% | 在压价抢购物车 | **critical** | 跟到略低于他，别一路砸 |
| 只有 1 家 + 售价跌 >5% | 可能是我们自己促销 | medium | 先确认是不是在做活动 |

**不做的**：不自动调价、不自动举报、不抓亚马逊页面。写操作的红线在这里同样生效。

## 何时使用 / 不使用

**使用：**
- 每天早上跟其他自动任务一起跑（`config/automations.yaml` 里的 `hijack-watch`）；
- 有人问"我们有没有被跟卖"。

**不使用：**
- 想看竞品动向 → `amz-competitor-watch`；
- 想查 Listing 有没有问题 → `amz-listing-audit`；
- 想算该不该降价 → `amz-ads-diagnose` / `amz-pricing`（价格决策不是这个技能的事）。

## 三层覆盖（2026-11-04 起，覆盖全部 ASIN 又不烧额度）

**问题**：185 个在卖 ASIN，全量每天查卖家数 = 5550 次/月，太贵；
只盯 Top 20 又会漏掉长尾被跟卖。

**解法**：用**免费的销量数据当哨兵**——跟卖的结果一定体现在自己销量上，
而销量是领星免费拉的。所以先筛后查：

| 层 | 干什么 | 成本 | 覆盖 |
| --- | --- | --- | --- |
| ① 主动盯 | **Top 25 每天**（占 49.9% 销售额） | 750 次/月 | 出单主力当天发现 |
| ② 被动筛 | `scripts/find_suspects.py` 每天跑：找"库存正常但销量骤降"的 SKU，只对它们查 | 约 150-300 次/月 | 长尾异常也能抓到 |
| ③ 兜底 | 周日全量查 185 个 | 740 次/月 | 每个 ASIN 每周至少一次 |

合计约 1690 次/月，**比全量每天（5550）省 70%，但覆盖是完整的**。

### 筛子判什么（三条，全部"跟自己比"）

1. **销量骤降**：最近 3 天日均 vs 前 10 天日均，跌 ≥40%
2. **排除断货**：FBA 可售 0 且没在途 → 那是缺货，不是跟卖（不用花额度查）
3. **排除低基数**：基准期日均不到 1 件的不判（1 件波动就是 100%，全是噪音）

实测（2026-11-04）：476 个 ASIN 筛出 5 个销量异常，其中 **3 个是断货**（不用查），
**2 个库存正常却跌 74%/49%** → 查了卖家数，都是 1 家 → 排除跟卖，
真正原因得看排名/广告/竞品。**花 3 次额度排除，而不是 185 次。**

## 前置

1. `config/watchlist.json` 填自己的 ASIN（留空则必须 `--asins` 传）；
2. 卖家精灵 MCP 已配置（`SELLERSPRITE_MCP_KEY`，见 `docs/DATA-SOURCES.md`）。

**成本**：卖家精灵按次计费，每个 ASIN 每天 1 次。20 个 ASIN = 每天 20 次、每月约 600 次。
只放**出单主力**，长尾不要放进来。

## 怎么跑

```bash
# 在仓库根目录执行；用 install_skills.py 软链安装的，把 skills/ 换成 ~/.agents/skills/ 下的实际路径
# 每天拉最新快照并比对（自动任务用这条）
python3 skills/amz-hijack-watch/scripts/run.py --fetch

# 不花额度，用已存快照重算（调阈值后复算用）
python3 skills/amz-hijack-watch/scripts/run.py

# 群消息摘要（一行一条，适合任意 IM 机器人）
python3 skills/amz-hijack-watch/scripts/run.py --format text

# 临时看几个 ASIN（不写 profiles）
python3 skills/amz-hijack-watch/scripts/run.py --asins B0D62SYW8S,B0ABC12345 --fetch
```

**第一次跑**只存快照、没有基准，会提示"快照不足"——第二天起才有变化可比。

## 输出

- `data/reports/hijack/<日期>_hijack.html`：变化清单（按严重度排序）+ KPI 卡；
- `data/raw/hijack/<日期>.json`：当天快照（不进 git，用来做次日比对）；
- 退出码：`1` = 有 critical（要人处理）；`0` = 无 critical；`2` = 数据缺失/快照不足。

## 口径与边界（读结论前必须知道）

1. **`sellers` 是 Keepa 采集的该 ASIN 在售 offer 数**，含 FBA/FBM，**不含**已断货未下架的；
   同一个卖家多个仓库不算多个。
2. **`buyBoxSellerIdHistory`（购物车卖家 ID 历史）我们的数据源拿不到**，
   所以"购物车被抢"只能用「卖家数 + 价格」间接推断——**不要说成"确定被抢了购物车"**。
3. 卖家数 1 家不等于安全：FBM 跟卖可能挂着但没库存，Keepa 不一定体现；
   反过来 2 家也可能是自己的两个账号。
4. 价格是 Keepa 的采集价，可能滞后，促销价/优惠券后价不一定反映。

## 阈值（改这里不用改代码）

`scripts/run.py` 顶部：

```python
PRICE_DROP_ALERT = 0.05   # 售价跌 >5% 才看
SELLER_NEW = 2            # 卖家数达到 2 家 = 有人跟卖
LOOKBACK_DAYS = 14        # 每次拉最近 14 天数据
```

## 与预警中心的关系

> 预警清单是否写入外部表格由你自己接，本仓库不内置任何外部同步。

## 变更记录

- **2026-11-04 新建**：调研了 3 个开源方案（[cx-keepa](https://github.com/comchatx/cx-keepa)、
  [cx-featured-offer](https://github.com/comchatx/cx-featured-offer)、
  [amazon-price-and-buybox-monitoring-tool](https://github.com/jakobowsky/amazon-price-and-buybox-monitoring-tool)），
  结论是行业标准做法看「Buy Box winner 变化 + 卖家数」；我们拿不到 Buy Box 卖家 ID，
  所以用卖家数 + 价格两个可得字段做判断，并在口径里写清这个局限。
