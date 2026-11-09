# amz-ads-diagnose

> 亚马逊广告诊断与复盘时用：先定目标再算盈亏线，按 CPC×转化×利润矩阵给处置，只出建议不改竞价。

| | |
| --- | --- |
| 类型 | 每日监控（自动） |
| 运行 | 每天 07:00（先 fetch_ads.py --days 3 拉数） |
| 有脚本 | 是 |

## 数据源

ads_asin_daily（领星 ad_campaign_product_report，ASIN 级日数据；92% 的行是 0 花费，只写有花费的）

## 逻辑链路（这是怎么算出来的）

① 三件套按顺序判，顺序不能反：

② 烧钱：花费 ≥¥15 且 0 单且点击 ≥8 → critical（真金白银在烧，最急）

③ ACOS 超线：有单且花费 ≥¥10 才看——花 ¥0.3 出 1 单 ACOS 能到 300%，那是分母太小不是问题；≥25% critical / ≥18% high（老板口径）

④ 花费骤增：今日 ≥ 昨日 2 倍且 ≥¥30 → high（预算被放大或竞价被抬）

⑤ 花费 Top15：即使无异常也展示钱花在哪——实测 Top15 里 12 个 0 单，单笔小但累积是真浪费

## 为什么这样设计 / 阈值依据

为什么不只看 ACOS：1 单变 2 单 ACOS 就砍半，样本小时绝对值无意义——所以先看『有没有烧钱』再看效率。ACOS 单位坑：领星返回 565 表示 565%，norm_pct() 归一化（>1 的当百分数除 100）。

## 输出去向

data/reports/ads/（HTML，异常清单+Top15）→ 云盘；退出码 1 = 有 critical

## 怎么调

阈值在 config/targets.json（acos_ceiling 0.18 / acos_critical 0.25）+ thresholds.yaml ads 段（high_spend_no_order 15 / min_clicks 8 / acos_min_spend 10）

---

本文档由 `scripts/gen_skills_kb.py` 生成；深度分析改脚本里的 KB 数据，描述/用法看 `skills/amz-ads-diagnose/SKILL.md`。