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

## 22 个技能

### 每天/每周都要跑（6 个）

| 技能 | 产出 |
| --- | --- |
| `amz-store-daily` | 单店 HTML 日报：销售额趋势、销量、ACOS、库存卡 |
| `amz-sku-daily` | 单品明细：昨日销量/广告/库存一段话 + SKU 可排序表格 |
| `amz-alert-center` | 十类经营预警汇总，分级输出（紧急/高/中/低） |
| `amz-stock-alert` | SKU 级断货预警：按 FBA 可售天数排队 |
| `amz-company-overview` | 多店一页纸总览（管理层看） |
| `amz-week-month-review` | 周/月复盘：环比、同比、各店对比 |

### 有问题时才用（8 个）

`amz-ads-diagnose`（广告效率异常）、`amz-listing-audit`（Listing 体检）、
`amz-listing-images`（主图像素/白底校验）、`amz-profit-review`（毛利与亏损榜）、
`amz-hijack-watch`（自己的 ASIN 被跟卖）、`amz-competitor-watch`（竞品价格/BSR 变化）、
`amz-review-watch`（自己的新差评）、`amz-compliance-tax-logistics`（能不能卖/能不能发/清关税务）

### 主动调研（4 个，需要卖家精灵密钥）

`amz-product-research`（类目值不值得进）、`amz-keyword-intel`（选词）、
`amz-brand-analytics`（品牌盘子）、`amz-review-insight`（竞品差评找改款机会）

其中前 3 个**没有脚本**，靠 Agent 直接调卖家精灵 MCP；`amz-review-insight` 有脚本但要 `--fetch` 才取数。
没有密钥时它们只能给方法，给不出数据。

### 其余 4 个

`amz-traffic-diagnose`（ASIN 流量结构）、`amz-sku-monthly`（月度 SKU 结构）、
`amz-calibration`（技能命中率校准）、`amz-inventory-alert`（店级库存分档，已合并进 `amz-stock-alert`）

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
