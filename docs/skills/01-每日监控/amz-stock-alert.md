# amz-stock-alert

> 库存紧时用：按 FBA 可售天数排队报断货风险；28 天仅为未校准运营候选预警，不判定官方低库存费。

| | |
| --- | --- |
| 类型 | 每日监控（自动） |
| 运行 | 每天 09:00 / 15:00 / 21:00 三次 |
| 有脚本 | 是 |

## 数据源

inventory_daily + sales_daily（SKU 级）

## 逻辑链路（这是怎么算出来的）

① 与 amz-inventory-alert 同源，但这是『SKU 级断货清单』——按可售天数升序排队，最急的排最前

② 输出补货建议只到『该补多少天』这一层：具体下单量、交期、起订量必须人工定（供应商数据不在系统里）

## 为什么这样设计 / 阈值依据

一天跑三次是因为断货不可逆：早上发现还能当天补，晚上发现就只能等隔天。

## 输出去向

文本清单（群消息用）+ HTML；28 天线标注为『未校准候选』，不判定亚马逊官方低库存费（那个要官方口径）

## 怎么调

skills/amz-stock-alert/scripts/run.py 顶部；官方低库存费线在 config/thresholds.yaml

---

本文档由 `scripts/gen_skills_kb.py` 生成；深度分析改脚本里的 KB 数据，描述/用法看 `skills/amz-stock-alert/SKILL.md`。