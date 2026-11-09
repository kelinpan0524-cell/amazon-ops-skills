# amz-hijack-watch

> 跟卖监控（我们自己的 ASIN）：每天看卖家数有没有从 1 变多、售价有没有被压低，发现跟卖立即告警；只报变化不抓页面。

| | |
| --- | --- |
| 类型 | 每日监控（自动） |
| 运行 | 周日 06:20 深查 Top100（日常全量由 scripts/watch_buybox.py 承担） |
| 有脚本 | 是 |

## 数据源

卖家精灵 keepa.trend（sellers 卖家数 + price，单 ASIN 一次，贵）

## 逻辑链路（这是怎么算出来的）

① 日常监控已换 asin.detail 批量方案（见 watch_buybox），本技能保留深查维度：一共几个卖家（buybox 只看购物车是谁的）

② 分级：卖家 1→≥2 critical；有跟卖+跌价>5% critical（压价抢购物车）；无跟卖跌>10% high；涨跌>50% 报数据异常（抓取读错）

③ 抓取健康：一轮 >25% 拿不到数据就报『变化清单不完整』——这时没告警是假的（开源叫 dead-man's switch）

## 为什么这样设计 / 阈值依据

见 SKILL.md。

## 输出去向

data/reports/hijack/ + 外部表格跟卖监控表

## 怎么调

SELLER_NEW/PRICE_DROP_ALERT/PRICE_SANITY 脚本顶部

---

本文档由 `scripts/gen_skills_kb.py` 生成；深度分析改脚本里的 KB 数据，描述/用法看 `skills/amz-hijack-watch/SKILL.md`。