# 架构：这个仓库怎么组织

目标不是"一套会自己变聪明的提示词"，而是**一条单向的数据/判断流水线**：原始事实进来，经过归一化和派生，由未校准的候选规则筛出建议，人工审批后到仓库外的系统去执行。反馈是离线的、事后的，不参与运行时判断。

## 单向主链（运行时）

```
① 原始事实与来源     ② 归一化数据      ③ 派生指标        ④ 候选/校准规则       ⑤ 建议            ⑥ 人工审批
─────────────────  ──────────────  ──────────────  ──────────────────  ───────────────  ───────────────
领星导出报表         data/normalized/  skills/_shared/  config/thresholds   skills 输出       人在卖家后台
亚马逊后台截图       sales_daily.csv   metrics.py 算     .yaml 读（不写死）    简报/异常/清单     自己判断/改
官方规范(SOURCES)    ads_daily.csv     （可复算）                            四段固定格式       价/改 Listing
主数据(sku_master)   inventory_daily
                    sku_master.csv
                    listing_current.csv（可选，手工）
                                          │
                                          ├──⑦a 业务外部执行（仓库外、永不自动）
                                          │     卖家后台 / ERP / 广告后台 / 供应商沟通
                                          │     config/automations.yaml::forbidden 写死
                                          │
                                          └──⑦b 报告归档（已授权的独立交付写）
                                                scripts/publish_report.py
                                                → 飞书云盘「示例公司｜亚马逊运营报告」
                                                配置：config/report_delivery.json
                                                索引：data/report-index.jsonl
                                                  │
                                                  └──⑦b-1 可选：同步示例公司工作台
                                                        （AMZ_WORKBENCH_URL + AMZ_WORKBENCH_SYNC_TOKEN
                                                         同时设置才 POST /openapi/reports/sync；
                                                         失败只标 workbench_status=failed，
                                                         飞书已归档不重复上传）
```

⑦a 和 ⑦b 是**两类完全不同的写**：
- **⑦a 业务写**：改价/改竞价/改 Listing/动库存/对外发消息。永不自动、永远在仓库外、人工手动执行。
- **⑦b 报告归档**：把仓库产出的 md/docx/xlsx/html 报告上传到指定飞书云盘文件夹。这是用户明确授权的独立交付写，不碰业务系统，不进 `forbidden`；失败时本地文件保留、非零退出、不假装成功。
- **⑦b-1 工作台同步**：⑦b 的可选延伸，把刚归档的报告元数据（date/kind/title/format/cloud_url）登记到示例公司工作台。它与 ⑦a 业务写无关，仍是同一交付链上的已授权写；未配置 env 时完全不触发，不影响飞书归档。

每一层的权威入口（老用户按这个追溯）：

| 层 | 权威文件 | 管什么 |
| --- | --- | --- |
| ① 外部事实 | `sources/SOURCES.md`、`reports/05-领星近一年参考标准.md` | 官方规范 URL、领星观测值、分页/样本范围 |
| ② 归一化 | `system/DATA-CONTRACT.md`、`scripts/import_lingxing.py` | 五张表（含可选 `listing_current`）的字段、单位、口径、入库规矩、degraded 门禁 |
| ③ 公式 | `skills/_shared/metrics.py`（+ `test_metrics.py`） | 全仓唯一一份算式与受限 YAML 解析，技能不许自写 |
| ④ 阈值 | `config/thresholds.yaml`（+ `config/CHANGELOG.md`） | 所有数字阈值，每条带来源/时间窗/边界/`calibration_status` |
| ⑤ 任务分级 | `reports/04-运营工作自动化分级.md` | 25 项日/周/月任务哪些能自动、哪些必须人做 |
| ⑥ 画像 | `profiles/company.md`、`profiles/products.md`、`profiles/competitors.md`、`profiles/industry.md` | 被证实的事实沉淀，每条带 `source`/`as_of`/`confidence` |
| ⑦b 报告归档 | `config/report_delivery.json`、`scripts/publish_report.py`、`data/report-index.jsonl` | 8 类报告 → 飞书云盘 8 个子目录的路由、归档命令、本地索引 |

## 反馈是离线的，不是运行时循环

```
                    每周日（amz-calibration，人工对账）
   ⑤ 建议 ────┐                                      ┌─── ④ 阈值（改后写 CHANGELOG）
              ├──→ judgements/*.md（运行时生成）────→ │
   实际结果 ──┘     记录 expected + review_on          └─── ⑥ 画像（confirmed/refuted 更新置信度）
```

关键约束：

- **运行时不闭环**。每天跑 `amz-sku-daily` / `amz-stock-alert` 时，脚本只读 ②③④，不会读"我上周命中率"来改今天的输出。
- **反馈只改 ④ 和 ⑥**。周日校准任务拉到期判断对账，命中率统计后：命中率 < 50% 的技能下周起默认只出观察不出建议；同一规则被证实 3 次升级为画像事实，被推翻 2 次降权；阈值修改只在这一步发生，且写 `config/CHANGELOG.md`。
- **⑦a 业务写永远在仓库外、永不自动**。仓库不注册任何写卖家后台/ERP/广告后台的动作；`config/automations.yaml::forbidden` 写死了永不自动做的动作。
- **⑦b 报告归档是已授权的独立交付写**。`scripts/publish_report.py` 把本地报告上传到指定飞书云盘文件夹，不碰业务系统；失败非零退出、本地文件保留、不追加索引。它与 ⑦a 是两类写，不要混为一谈。可选的工作台同步（⑦b-1）是这条交付链的延伸，不是业务写。

这样设计是为了避免"自迭代"退化成"自我发挥"：如果当天的判断会被当天的命中率反馈影响，模型/脚本就会自己调自己的阈值，越调越偏。

## 四张画像怎么来

| 懂什么 | 画像文件 | 数据从哪来 | 多久更新 |
| --- | --- | --- | --- |
| 懂公司经营 | `profiles/company.md` | 领星：店铺/ASIN 销量、库存周转、广告花费（**毛利/成本未校准，不进画像**） | 每月 + 月底核对 |
| 懂我们的商品 | `profiles/products.md` | 领星产品表现 + 飞书知识库（第五章汽配特有知识）+ 主数据（OE 号/车型） | 每次上新、每次 SKU 变动 |
| 懂同行 | `profiles/competitors.md` | 人喂的 5–10 个 ASIN 的价格/评分/评论数/BSR 相对变化 | 每周 |
| 懂行业 | `profiles/industry.md` | 知识库 + 官方政策/关税/合规变化 | 每季度，遇政策变即更 |

每条事实的写法：

```yaml
- claim: "主力品类是控制臂，占近 90 天销售额的 41%"
  value: 0.41
  confidence: high          # high / medium / low / needs_data
  source: "领星 利润-ASIN 2026-10-01~2026-12-31 报表"
  as_of: 2026-11-04
  evidence: "data/raw/2026-11-04/lingxing_profit_asin.jsonl#rows=312"
```

没有 `source` 和 `evidence` 的条目，不进画像。

## 判断怎么写、怎么对账

`judgements/2026-11-04-listing-audit.md`（运行时生成，不进 git）：

```yaml
id: J-20261104-01
skill: amz-listing-audit
asin: B0XXXXXXX
claim: "标题缺少车型适配信息，预计影响点击率"
action: "建议改标题，加 YMM"
expected: "改后 14 天会话数 +10% 以上"
status: open        # open / confirmed / refuted / expired
review_on: 2026-11-18
```

到 `review_on` 那天，周日校准任务去领星拉真实数据，把 `status` 改成 confirmed 或 refuted，并写一句结论。

## 硬约束

- **只增不删**：画像与判断都只追加，过期标 `outdated` 并写被谁取代。
- **不许自己调权**：技能不能改自己的阈值；阈值只能由周日校准任务改，且留痕。
- **三种数据分开**：领星给的是账户事实，官方规范是平台规则，模型推理的是假设。三者不混写，输出时标等级。
- **写操作永不自动**：`DIAGNOSE → DRAFT → RELEASE_PREP → APPROVED_WRITE`，人工不批不出门。
- **低置信度不出建议**：`confidence: low` 或 `needs_data` 的事实只能作为"待补"，不能拿来算结论。
- **车标硬阻断**：文案、图片、Fitment 卡片、Listing 建议中出现车标，一律 HOLD，移除/替换并人工复核；正常车型适配文字不因此自动阻断。规则适用于全部汽配类目，不限于控制臂/衬套/悬置/球头/拉杆。

## 数据通路

见 [`system/DATA-CONTRACT.md`](./DATA-CONTRACT.md)。当前唯一在用的是 A：领星后台导出 Excel/CSV → `scripts/import_lingxing.py` 归一化。B（领星 MCP）和 C（开放平台 API）在文档里保留为备选，未启用。
