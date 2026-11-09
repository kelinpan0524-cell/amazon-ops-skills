# 数据契约：领星的东西怎么进来，技能怎么用

技能不认识"领星"，只认识**标准化后的表**：四张必填表 + 一张可选手工表。换数据源只改适配器，技能不动。

> 本文件是字段的唯一权威入口：字段名、单位、口径、入库规矩都在这里定。
> 公式去 `skills/_shared/metrics.py`，阈值去 `config/thresholds.yaml`，外部事实去 `sources/SOURCES.md`，领星近一年观测与分页限制去 `reports/05-领星近一年参考标准.md`，报告归档路由去 `config/report_delivery.json`。

## 三个口径限制（读字段前必须知道）

| 限制 | 本文件的体现 | 不能怎么用 |
| --- | --- | --- |
| **领星毛利/成本未校准** | 四张表里没有独立的 `profit` / `gross_margin` 权威字段；`inventory_daily.unit_cost` 是领星字段占位，**不代表已校准成本** | 不拿它算盈亏平衡 ACOS、不拿它当利润基准；广告诊断只看花费/销售绝对值 |
| **默认库存只算 FBA 可售** | `inventory_daily` 只有 `fba_available` / `fba_inbound`；**本地仓/海外仓/AWD 不在本表**；FBA 站点视图可能重复反映同一物理库存 | `fba_inbound` 单独披露但**不加到可售**；不跨站点相加；不输出"全量库存" |
| **全年 total_sum 不替代每日明细** | 本表只描述 `data/normalized/` 里的每日粒度；`reports/05` 的领星全年汇总是观测参考，ASIN 级/月度级当时只回第 1 页（样本/不全） | 不拿全年 total_sum 反推每日结构；不把 total_sum 当技能输入 |

## 三条通路（2026-11-04 修订：MCP 已成为主力）

| 通路 | 现状 | 怎么做 | 局限 |
| --- | --- | --- | --- |
| **A. 领星 MCP（主力）** | **每天在跑** | `scripts/fetch_lingxing.py` 自动拉 `shop_daily`（店铺×天）；店铺组在 `config/shops.json`；Mac Mini 06:30 定时 | 必须用只读账号生成密钥；QPS=1 需节流；只覆盖店铺级 total_sum |
| **B. 导出报表（备选/补明细）** | 可用 | 领星后台导出 Excel/CSV → `scripts/import_lingxing.py` 归一化 → `data/normalized/` | 手动；但 ASIN/SKU 级明细只能走它（MCP 的店铺级口径给不了） |
| **C. 开放平台 API** | 未申请 | 领星开放平台申请 → 密钥进环境变量 → 另写拉数脚本（未实现） | 要企业资质、限流、字段以官方为准 |

**一句话分工**：**店铺级日报/周报/预警走 A（MCP 自动）**；**ASIN/SKU 级明细走 B（导出报表）**；
C 是将来想完全脱离手工导出时的路线（属 `reports/04` 自动化分级的下一阶段）。

两条在用通路各管一组表，互不重叠：`shop_daily` 只由 A 产出，
`sales_daily`/`ads_daily`/`inventory_daily`/`sku_master` 只由 B 产出。

## 标准化表（4 张必填表 + 1 张可选手工表）

### 1. `sales_daily`（销量与流量）
```yaml
date, marketplace, asin, sku, title, sessions, page_views, units, unit_session_pct, revenue, currency
```
来源：领星 产品表现 / 业务报告；用途：Listing 体检、转化诊断、趋势、每日简报。

### 2. `ads_daily`（广告）
```yaml
date, marketplace, campaign, ad_group, targeting, match_type, impressions, clicks, spend, sales, orders, acos, roas
```
来源：领星 SP/SD/SB 日报与小时报；用途：ACOS 诊断、词根分析、否词。

### 3. `inventory_daily`（库存与补货）
```yaml
date, asin, sku, fba_available, fba_inbound, days_of_supply, sell_through, replenish_suggestion, unit_cost
```
来源：领星 FBA 库存与补货视图；用途：断货预警、补货建议（只建议不执行）。

**库存口径（2026-11-04 定）**：
- 断货/周转类结论只把 `fba_available` 当"可售"。
- `fba_inbound`（在途）单独披露，**不算可售**。
- 本地仓/第三方仓/AWD **不在本表**——凡输出库存结论的脚本必须逐次披露这个缺口，禁止把它表述成全量库存。
- FBA 站点视图（CA/MX/BR）可能重复反映同一物理库存，**禁止跨站点相加**（见 `reports/05` §4.2 对账）。
- `unit_cost` 是领星字段占位，**未校准**，不进入任何利润/盈亏计算。

### 4. `sku_master`（商品主数据，含汽配关键字段）
```yaml
sku, asin, oe_number, vehicle_make, vehicle_model, year_from, year_to, position, material,
cost, list_price, weight_g, certifications, hs_code
```
来源：我们的主数据 + 知识库 + 领星产品档案；**这是汽配的命门**，缺字段的技能一律输出 `needs_data`。

- `cost` 字段当前未录入校准值，留空是正常的；不要拿领星毛利反推。
- `oe_number` / `year_from` / `year_to` 缺失率 >10% 时，fitment 类分析只出观察不出结论（阈值见 `config/thresholds.yaml::fitment`）。

### 5. `listing_current`（可选第 5 张，手工维护的 Listing 快照）
```yaml
asin, title, bullets_count, description_len, has_a_plus, main_image_path
```
- **来源**：手工从卖家后台/第三方工具导出的 Listing 快照，**脚本不自动抓**。
- **放置路径**：`data/normalized/listing_current.csv`。
- **用途**：`amz-listing-audit` 用它查标题字符数、五点数、描述长度、A+ 有无、主图路径是否存在，并对 `title` 文字做车标硬阻断扫描。
- **缺它时的降级**：`amz-listing-audit` **只做 fitment 命门**（OE/年款/车型填写率），标题/五点/描述/A+ 整段标"需人工复核"，**不假装查过**。
- `main_image_path` 指向本地图片文件；脚本只检查路径是否存在，不判断图片合规（图片合规由 `skills/amz-listing-images/scripts/img_check.py` 负责）。
- 这张表是快照，需按 `system/FRESHNESS.md` 关注新鲜度；它反映的是导出时刻的 Listing 状态，不是实时。

### 6. `shop_daily`（店铺组 × 天，自动化拉取）
```yaml
shop, date, units, revenue, net_revenue, orders, sessions, page_views, spend, ad_sales, acos, return_rate, fba_available, available_inventory, units_yoy_ratio, fetched_at
```
- **来源**：`scripts/fetch_lingxing.py` 从领星 MCP 自动拉取（店铺组定义在 `config/shops.json`；
  每天每店一次 `query_product_performance_asin_lists` 的 total_sum）。
- **口径**：USD、下单口径（date_type=purchase）、店铺组多站点合并；**毛利/利润字段不落表**（未校准红线）。
- **幂等**：同 shop+date 重拉替换，异日期追加（与手工导入同一语义）。
- **用途**：`amz-store-daily`（单店日报）与 `amz-company-overview`（多店总览）的唯一数据源。
- **注意**：`units_yoy_ratio` 是领星给的同比（观测参考）；`available_inventory` 含预留/在途入库
  （领星「FBA可售+待调仓+预留+入库中」口径），比 `fba_available` 宽，展示时必须注明。

## 入库规矩（`scripts/import_lingxing.py` 已实现）

- 原始文件进 `data/raw/<YYYY-MM-DD>/`，**永不修改**；归一化结果进 `data/normalized/`，可重算。
- 每份入库写一条 `data/MANIFEST.md`：日期、表名、行数、缺字段、quality 状态。
- **degraded 门禁按关键字段算**：脚本把字段分"关键字段"和"可选观察列"（如 `inventory_daily.unit_cost`、`sales_daily.title`/`marketplace`/`currency`、`ads_daily.acos`/`roas` 等不参与判定）；**关键字段缺失率 >20%** 才把整表标 `quality: degraded`，相关技能只出观察不出建议。可选列缺失不报。
- **同日同名防覆盖**：`data/raw/<日期>/` 里已有同名文件时，旧文件先移到 `data/raw/<日期>/superseded/`（加 `HHMMSS-` 时间戳前缀），再放新文件；只增不删。
- `listing_current.csv` 不走 `import_lingxing.py`（它不是领星导出），由人手工放到 `data/normalized/listing_current.csv`。

## 与期初口径的对齐（重要）

- 金额单位统一为 **USD 原值**：领星按 `currency_code=USD` 返回，系统不做任何币种换算。
- 时间统一**北京时间**；平台侧 UTC 时间戳在适配器里转换。
- ASIN 大小写、SKU 前后空格、市场站点代码（US/UK/DE…）在适配器里统一，技能层不做清洗。

## 参考观测（不是字段定义的一部分）

`reports/05-领星近一年参考标准.md` 记录了 2025-11-04 ~ 2026-11-04 的领星只读观测（全量销售额、ACOS/TACOS、退货率、CPC、FBA/本地仓库存件数等）。这些是**观测参考**，不是公司已校准目标；其中毛利/成本字段按上面"三个口径限制"处理，不进阈值、不进画像。具体数字、分页限制与对账结论以 `reports/05` 原文为准，本文件不复述。
