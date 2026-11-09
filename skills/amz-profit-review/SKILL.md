---
name: amz-profit-review
description: 用户问「这个月赚了多少/哪个店亏」时才用：毛利率、分店对比、亏损 ASIN 榜单、环比趋势。只算录了采购成本的 ASIN、不含头程，口径写在报告里；没有成本数据时直说算不了。
version: 1.0.0
author: Kelin Pan
license: private
last_verified: 2026-11-04
review_by: 2027-05-04
platforms: [macos, linux]
metadata:
  automation:
    tags: [亚马逊, 利润, 毛利, 复盘]
    related_skills: [amz-week-month-review, amz-company-overview]
---

# 利润复盘

**跟总览里的「毛利情况」有什么不同**：总览那块是当天快照；这个报告是周/月复盘——
看趋势、看亏损榜、看哪个店在恶化。

## 怎么跑

```bash
# 在仓库根目录执行；用 install_skills.py 软链安装的，把 skills/ 换成 ~/.agents/skills/ 下的实际路径
# 周报（默认取本周）
python3 skills/amz-profit-review/scripts/run.py --period week

# 指定某周
python3 skills/amz-profit-review/scripts/run.py --period week --anchor 2026-11-03

# 月报
python3 skills/amz-profit-review/scripts/run.py --period month --anchor 2026-10

# 群消息摘要
python3 skills/amz-profit-review/scripts/run.py --period week --format text
```

自动化：每周一 08:30、每月 3 号 09:30（`config/automations.yaml`）。

## 报告里有什么

| 板块 | 内容 |
| --- | --- |
| KPI | 销售额、毛利、毛利率（带目标 + 环比）、亏损 ASIN 数 |
| 分店毛利 | 每店销售额/毛利/毛利率/环比/亏损数/状态 |
| 亏损榜 | 按亏损额排 Top15，带采购单价 |
| 口径说明 | 覆盖率、不含头程、阈值 |

## 口径（读之前必须知道）

1. **不含头程物流**：领星扣了采购成本 + FBA 配送费 + 佣金，但头程没录（实测恒为 0），
   所以毛利率是**上限值**
2. **只算有采购成本的 ASIN**（`has_cost=1`）。本期实际覆盖率约 25%——
   把"没录"当"成本 0"会让毛利率虚高（实测差 8 个点：29.9% vs 21.5%）
3. **覆盖率上去后毛利率会变**（通常是降低）。成本补全了要重跑月度对比

## 阈值

`config/targets.json` 的 `profit` 段：

```json
"gross_margin_target": 0.30,     // 目标
"gross_margin_floor": 0.15,      // 低于这个算偏低
"gross_margin_critical": 0.0     // 低于 0 = 亏损
```

依据是 2026-11-04 实测：口径内毛利率 29.9%、中位 30%、12% 的 ASIN 亏损。

## 变更记录

- **2026-11-04 新建**：用户要求利润要有专门报告 + 周月自动化。
  跟 `amz-company-overview` 的分工：那个是每天扫一眼的快照，这个是周月的趋势和排名。
