# 亚马逊运营技能包（22 个技能，MIT）

> 把「店铺 / SKU / 广告 / 库存 / 评论 / 竞品」的经营数据变成**能直接看的 HTML 报告和预警清单**。
> 给运营、采购、老板用；所有写操作（改价、停广告、下单）永远停在建议，人批准才动。

**30 秒看效果**（不用任何密钥、不用联网）：

```bash
git clone <this-repo> && cd amazon-ops-skills
cp config/shops.example.json config/shops.json
AMZ_DATA_DIR=examples python3 skills/amz-store-daily/scripts/run.py
# → data/reports/shop/shop_a/2026-11-08_shop_a.html
```

`examples/` 里是合成数据（两家假店铺、三个假 SKU、90 天）。详见 [examples/README.md](examples/README.md)。

---

## 先说三条口径限制（读任何数字之前必须知道）

| 限制 | 含义 | 后果 |
| --- | --- | --- |
| **成本/毛利未校准** | 只有录了采购成本的 ASIN 才能算毛利，且不含头程、关税、仓储 | **不能当利润表用，也不能用 ACOS 反推盈亏平衡** |
| **库存只算 FBA 可售** | 不含在途、国内仓、海外仓、3PL | 可售天数是下限，不是全貌 |
| **数据 T+1** | 平台的经营数据次日才齐 | 报告默认回退到"最近一个完整日"，不会拿半天数据冒充一天 |

另外：金额**全部是 USD 原值**，本仓库不做汇率换算。

---

## 装到你的 Agent 里

技能是标准的 `SKILL.md` 目录，任何能读技能、能跑 `python3` 的客户端都能用：

| 客户端 | 怎么装 |
| --- | --- |
| Claude Code | `python3 scripts/install_skills.py --target claude` |
| Codex / ZCode | `python3 scripts/install_skills.py --target agents` |
| Trae | 设置里把技能目录指到本仓库的 `skills/` |
| WorkBuddy / 豆包 | `python3 scripts/install_skills.py --pack ~/amz-skills.zip` 后导入 |

细节（凭证放哪、没有终端怎么办、故障排查）见 [docs/CLIENTS.md](docs/CLIENTS.md)。

**依赖**：Python ≥ 3.9，纯标准库。
可选：`openpyxl`（仅导入 .xlsx）、`numpy` + `Pillow`（仅 `amz-listing-images`）。

---

## 22 个技能逐个说明

每个技能都是"一句话能说清干什么、要什么数据、产出什么东西"。表里的数据表名对应
[`system/DATA-CONTRACT.md`](system/DATA-CONTRACT.md) 的字段定义；报告统一落在 `data/reports/` 下。
更细的算法链路见 [`docs/skills/`](docs/skills/)。

### 一、日程型：每天 / 每周都会用（6 个）

| 技能 | 干什么 | 要什么数据 | 产出 | 怎么说 |
| --- | --- | --- | --- | --- |
| `amz-store-daily` | 单店经营日报：KPI 卡（带环比/基准/目标）、30 天销售额趋势、销量柱、ACOS×花费双轴、库存卡 | `shop_daily` | `data/reports/shop/<店>/<日期>_<店>.html` | 「昨天怎么样」「这个店怎么样」 |
| `amz-sku-daily` | 单品明细：昨日销量/广告/库存一段话讲完，异常单列，附 SKU×ASIN 可排序表格 | `shop_daily` `sales_daily` `ads_asin_daily` `inventory_daily` | `data/reports/daily/<日期>_daily.html` | 「哪些 SKU 出问题」「单品卖得怎么样」 |
| `amz-alert-center` | 十类预警汇总（断货/断货风险/销售骤降/周趋势/有花费无单/ACOS 两档/退货两档/数据断供/目标落后），分级输出；**退出码 1 = 有紧急项要人看** | `shop_daily` + `config/alert_rules.json` | `data/reports/alerts/<日期>_alerts.html`；`--format text` 出可直接发群的三五行 | 「今天有什么异常」「哪里出事了」 |
| `amz-stock-alert` | SKU 级断货预警：按 FBA 可售天数排队（急 <10 天 / 关注 10–21 / 候选 21–28），给补货复核优先级 | `inventory_daily` + `sales_daily`（近 28 天） | `data/reports/stockout/<日期>_stockout.html` | 「哪些要补货」「会不会断货」「还能卖几天」 |
| `amz-company-overview` | 多店一页纸总览：汇总 KPI、店铺对比、各店趋势与异常摘要（不含 SKU 明细） | `shop_daily` + `config/shops.json` | `data/reports/mgmt/<日期>_overview.html` | 「多店整体怎么样」（老板/管理层看） |
| `amz-week-month-review` | 周/月复盘：本期 vs 上期环比、vs 去年同比、各周期趋势、店铺贡献 | `shop_daily`（周报≥14 天、月报≥2 月、同比≥13 月） | `data/reports/review/…html` | 「这周怎么样」「这个月怎么样」 |

### 二、事件型：出问题才用（8 个）

| 技能 | 干什么 | 要什么数据 | 产出 | 怎么说 |
| --- | --- | --- | --- | --- |
| `amz-ads-diagnose` | 广告诊断：先定目标再算盈亏线，按 CPC×转化×利润矩阵给处置建议（只出建议，不改竞价） | `ads_daily` + 成本结构（拿货/头程/配送费/佣金） | `data/reports/ads/…html` | 「ACOS 太高」「烧钱不出单」「要不要加预算」 |
| `amz-listing-audit` | Listing 体检：OE 号与年款适配、标题/五点/主图缺项，缺的标「待补」 | `sku_master`（可选 `sales_daily` 排优先级） | `data/reports/listing/…html` | 「帮我体检这个 listing」 |
| `amz-listing-images` | 主图合规：白底、尺寸、占比像素校验，副图检查，适配车型卡（只出 DRAFT） | 图片文件 + Pillow/numpy | 检查结论（技术通过仍需人工看车标） | 「这张主图合不合规」 |
| `amz-profit-review` | 毛利复盘：毛利率、分店对比、亏损 ASIN 榜、环比趋势（只算录了采购成本的，不含头程） | `profit_daily`（`has_cost=1`） | `data/reports/profit/…html` | 「这个月赚了多少」「哪个店在亏」 |
| `amz-hijack-watch` | 跟卖监控（**自己的** ASIN）：卖家数是否从 1 变多、售价是否被压低 | `config/watchlist.json` + 卖家精灵 | `data/reports/hijack/<日期>_hijack.html` + 快照 | 「有没有被跟卖」「购物车还在不在」 |
| `amz-competitor-watch` | 竞品监控（**别人的** ASIN）：5–10 个同货架 ASIN 的价格/评分/评论/BSR/卖家数变化 | `config/competitors.json` + 卖家精灵 | `data/reports/competitor/…html` | 「竞品最近怎么动」「价格变了吗」 |
| `amz-review-watch` | 评论监控（自己的 ASIN）：只看**新出现**的 1–3 星差评，老评论不重复报 | `config/watchlist.json` + 卖家精灵 | `data/reports/review/<日期>_review.html` + 快照 | 「有没有新差评」 |
| `amz-compliance-tax-logistics` | 合规门禁：禁限售、认证标签、VAT/GST/Nexus、HS/关税、FBA/FBM/3PL、危险品；没有一手证据一律标 `unverified` | 产品属性 + 目标国 + 平台 | 门禁结论（不下法律/税务结论） | 「这个 SKU 能不能卖」「怎么清关」 |

### 三、项目型：主动调研（4 个，需要卖家精灵密钥）

| 技能 | 干什么 | 产出 | 怎么说 |
| --- | --- | --- | --- |
| `amz-product-research` | 类目/细分市场值不值得进：容量、竞争格局、价格带、新品成功率、需求趋势 | GO / CAUTION / AVOID 结论 | 「这个类目值不值得进」 |
| `amz-keyword-intel` | 选词：搜索量、竞争度、PPC、竞品 ASIN、类目趋势 | 结构化调研报告 | 「选什么词」「这个词竞争大不大」 |
| `amz-brand-analytics` | 一个品牌在类目的盘子：在售 ASIN 数、销量分布、份额、新品起势 | 品牌分析报告 | 「这个品牌盘子多大」 |
| `amz-review-insight` | 竞品差评归类（装不上/尺寸/质量/物流/描述不符/价格），每类给「你能怎么用」 | 改款/选品机会清单 | 「从差评里找机会」 |

> 前 3 个**没有脚本**，靠 Agent 直接调卖家精灵 MCP；`amz-review-insight` 有脚本但要 `--fetch` 才取数。

### 四、其余（4 个）

| 技能 | 干什么 | 要什么数据 | 产出 |
| --- | --- | --- | --- |
| `amz-traffic-diagnose` | 单个 ASIN 的流量结构：核心词、前 3 词占比、自然词覆盖、有曝光无转化的词 | 快照 + 卖家精灵 | 诊断结论（该修 listing 还是补词） |
| `amz-sku-monthly` | 月度单品结构：卖什么、怎么赚、压在哪儿、广告占比 | `sales_daily`（可选 `ads_daily`） | 文本 + HTML 复盘 |
| `amz-calibration` | 每周日校对判断命中率（用 `judgements/*.md`），命中率低的规则降权 | `judgements/*.md` + `thresholds.yaml` | 校准报告 + 降权建议（只在定时任务里跑） |
| `amz-inventory-alert` | 店级库存分档（急/关注/注意/正常）+ 补货建议 | `shop_daily` + `config/targets.json` | `data/reports/inventory/…html`（已合并进 `amz-stock-alert`，默认关闭） |

### 所有技能的共同点

- **只读不写**：只产报告和建议，不改价、不停广告、不下采购单、不写平台后台；
- **缺数据不编**：缺表直接报 `needs_data` 或退出码 2，不填 0、不填示例值；
- **口径一致**：金额 USD 原值，指标公式只在 `skills/_shared/metrics.py` 一处；
- **可组合**：日报看现象 → 预警看风险 → 诊断技能看原因，同一份 CSV 反复用。

---

## 数据从哪来（两条路）

### 路一：CSV（不依赖任何第三方服务）

按 [system/DATA-CONTRACT.md](system/DATA-CONTRACT.md) 的表结构准备 CSV，放进任意目录：

```bash
AMZ_DATA_DIR=/path/to/your/csv python3 skills/amz-store-daily/scripts/run.py
```

### 路二：接领星 ERP（自动化拉数）

```bash
export LINGXING_MCP_URL="https://openmcp.lingxing.com/mcp-servers/lingxing-mcp"
export LINGXING_MCP_KEY="<你的密钥>"
python3 scripts/fetch_lingxing.py --days 30
python3 skills/amz-store-daily/scripts/run.py
```

卖家精灵（市场情报）同理，见 [docs/DATA-SOURCES.md](docs/DATA-SOURCES.md)。
凭证也可以写进 `config/mcp.local.json`（GUI 客户端拿不到 shell 变量时用这个）。

---

## 它不做什么

- **不改价、不停广告、不下采购单**：所有技能只出建议，写操作留给人和平台后台。
- **不算利润表**：成本未校准，毛利只做"变化方向"参考。
- **不给你编数**：缺数据就报 `needs_data` 或退出码 2，不拿 0 或示例值冒充。

## 退出码约定（写定时任务的人看）

| 码 | 含义 | 定时任务怎么处理 |
| --- | --- | --- |
| 0 | 成功，无需处理 | 不打扰 |
| 1 | 成功，但有 critical/high 要人看 | 推送叫人 |
| 2 | 数据缺失 / 前置条件不满足 | 提醒补数据，别当告警 |
| 3+ | 程序错误 | 报错排查 |

---

## 目录

```
skills/       22 个技能 + _shared/（共享算式层）
config/       模板（*.example.json）+ 阈值 + 预警规则
examples/     合成数据，装完就能跑
docs/         上手、客户端、数据源、工作流
scripts/      取数、导入、质检、安装
system/       数据契约与架构说明
```

改代码看 [CONTRIBUTING.md](CONTRIBUTING.md)；版本变化看 [CHANGELOG.md](CHANGELOG.md)。

## 许可证

MIT，见 [LICENSE](LICENSE)。技能里引用的第三方数据源（领星、卖家精灵、亚马逊前台）各自受其服务条款约束。
