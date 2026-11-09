---
name: amz-alert-center
description: 经营预警中心：按规则表扫描经营、数据新鲜度与竞对风险，分级输出可推送的预警清单。
version: 1.0.0
author: Kelin Pan, ZCode
license: private
last_verified: 2026-11-04
review_by: 2027-02-04
platforms: [macos, linux]
metadata:
  automation:
    tags: [亚马逊, 预警, 监控, 自动化]
    related_skills: [amz-store-daily, amz-week-month-review, amz-stock-alert]
---

# 经营预警中心

**这是给运营减负的核心技能**：不用每天翻后台，只处理「机器已经筛出来该处理的事」。
规则表在 `config/alert_rules.json`（改阈值不用改代码），输出分级清单 + 可推送的摘要。

## 预警规则（每条都在规则表里可开关）

| 预警 | 级别 | 触发条件（以 `config/alert_rules.json` 为准） | 当天动作 |
| --- | --- | --- | --- |
| 已断货 | critical | FBA 可售 = 0 但近 7 天有销量 | 紧急补货/转 FBM/停广告止损 |
| 销售骤降 | high | 日销售额较前一完整日跌 >30% | 查库存→Listing→竞品价 |
| 有花费无订单 | high | 日广告花费 >50 USD 且 0 单 | 当天查投放 |
| 数据延迟 / 断供 | low / high | 最近完整日=昨天为正常；前天且最近拉取成功=官方延迟 low；最近拉取失败=拉取失败 high；≥3 天无完整数据=断供 high | 先看 `data/logs/fetch_status.json`，再查定时任务或领星授权 |
| 断货风险 | high | 可售天数（粗算）< 14 天 | 核对在途，走补货 |
| ACOS 偏高 / 严重偏高 | medium / high | 日 ACOS >18% / >25% | 查高花费低转化活动，出否词建议 |
| 退货率接近 / 超过收费线 | medium / high | 日退货率 >8%；近 30 天口径 >9.1% | 查退货原因，适配不符查 fitment |
| 周趋势下滑 | medium | 近 7 天 < 前 7 天 15% | 周会归因 |
| 月度目标落后 | high | 时间进度 ≥40%，达成率÷时间进度 <0.8 | 拆流量、转化、广告与库存原因 |
| 毛利率偏低 / 为负 | high / critical | 领星口径毛利率 <15% / <0 | 先核采购成本、配送费与售价，不自动改价 |
| 跟卖预警 | high | 最新快照 sellers>1 | 核对卖家与价格，人工处理 BuyBox |

> 同比下滑**不在这里**：月同比请看 `amz-week-month-review` 的同比栏；历史不足时会明确写「不可用」，
> 不把缺失基期算成 0 或 100% 变化。

## 人工确认边界（本技能只叫人不代做）

- 预警只做「发现 + 给建议动作」；**改价、停广告、下单、改 Listing、对外沟通一律人工执行**；
- 退出码 `1` 只表示「有 critical/high 需要人看」，**不代表脚本可以替你做决定**；
- 每条预警的 `action` 是建议不是指令，按实际情况判断（比如"竞品断货"可能是暂时缺货，不必立刻加价）；
- 阈值与校准依据都写在 `config/alert_rules.json`；调整配置即可，不必改代码。

## 用法

```bash
# 全量扫描（默认看最新完整日）
python3 skills/amz-alert-center/scripts/run.py

# 只看某一店 / 只出 critical+high（推送用）
python3 skills/amz-alert-center/scripts/run.py --shop shop_a --min-level high

# 生成可推送的纯文本摘要（喂给任意 IM 机器人）
python3 skills/amz-alert-center/scripts/run.py --format text
```

## 输出

- 默认：`data/reports/alerts/<日期>_alerts.html`（红色分级清单，可直接发群）
- `--format text`：stdout 纯文本（3-5 行，适合群机器人卡片）
- 退出码：**有 critical/high → 非零（1）**，便于定时任务据此决定要不要叫人

## 设计原则（为什么这么做）

1. **宁可漏报噪音，不可漏掉真事**：critical/high 走「立即推」，medium 进日报摘要，low 只列报告；
2. **每条预警必须带「该怎么办」**：只报「跌了」没有用，必须给下一步动作；
3. **阈值全在配置里**：`config/alert_rules.json` 每条带 `why` 与 `action`，校准就改这里；
4. **不自动执行**：预警只负责叫人和给建议，改价/停广告/下单永远人工做；
5. **数据断供也算预警**：上游断了没人发现是最隐蔽的事故（比销售下滑更危险）。

## 边界

- 成本未校准 → ACOS 类预警只说「效率高低」，不说「亏不亏」；
- 库存只算 FBA 可售 → 断货预警是「FBA 还能卖几天」，不是全公司库存；
- 竞品/跟卖类预警依赖卖家精灵数据，未配时该条跳过并在输出里注明。

## 何时使用 / 不使用

**用**：每天定时扫一遍（Mac Mini 07:00）；上班先看有没有 critical/high；周会前确认遗留风险。
**不用**：看趋势（用 `amz-week-month-review`）、看单店明细（用 `amz-store-daily`）。

## 最小输入

`data/normalized/shop_daily.csv` + `config/alert_rules.json`。
规则表缺失或损坏时**不静默用默认值**——直接报错，避免"以为在扫其实没扫"。

## 失败降级

| 情况 | 行为 |
| --- | --- |
| 无数据 | 退出码 **2**（数据缺失，不是告警） |
| 某条规则配置写错（缺 level/threshold） | 该条跳过并在 stderr 提示，其余照跑 |
| `seller_count` 等可选字段缺失 | 对应检测跳过（不拿"主卖家存在"冒充"只有一家"） |
| 所有规则都关掉 | 输出「所有规则均未启用」并以 0 退出（不假装跑过） |

## 人工确认边界

- 见上文「单条预警的动作是建议不是指令」；
- 预警**不写任何业务系统**：不改价、不停广告、不下单、不发消息；
- 每天最多推一次摘要，避免告警疲劳（同一问题反复推 = 没人再看）。
