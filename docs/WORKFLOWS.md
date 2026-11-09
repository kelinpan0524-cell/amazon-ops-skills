# 常用工作流（每日 / 每周 / 每月）

这份文档回答一个问题：**我现在要做一件具体的运营事，敲哪条命令、需要什么数据、输出长什么样、跑挂了怎么办。**

不假设你看过任何聊天记录。所有命令都在仓库根目录执行；所有输出都是只读报告或异常清单，**不会**自动改卖家后台任何东西。

> 三个口径限制（每次输出都会重复，但你必须先记住）：
> ① 领星毛利/成本未校准，不做利润基准；② 默认库存只算 FBA 可售，在途≠可售，本地仓/第三方仓不在表里；③ 全年 `total_sum` 不替代每日明细。

---

## 0. 先做：自检与排障（任何时候跑）

### 0.1 跑通全仓自检（30 秒，用合成数据，不碰真实数据）

```bash
python3 scripts/selftest.py
```

- **最小输入**：无。脚本自己在临时目录造合成数据，跑完自动清理。
- **输出**：每个技能一行 `✓ <技能名>（N 行输出）`，最后一行 `全部通过` 或 `N 项失败`。
- **退出码**：0 = 全绿；非 0 = 有技能跑挂。
- **失败降级**：
  - 看到 `✗ <技能>：退出码 N`：先跑 `python3 skills/_shared/test_metrics.py` 看算式库是否全绿；再跑 `python3 skills/_shared/test_thresholds.py` 看阈值读取是否正常。
  - 这一步**不依赖**你有没有导入真实数据，所以 clone 下来第一件事就该跑。

### 0.2 看数据新不新鲜

```bash
python3 scripts/check_data_freshness.py
```

- **输出**：没输出 = 数据是新的（≤3 天）；有输出 = 告诉你哪张表过期了。
- **失败降级**：提示"还没导入过领星数据"就先去第 1 步导入。

### 0.3 看规则有没有过期（图片规范、税率、FBA 费用等）

```bash
python3 scripts/check_freshness.py --all
```

- **输出**：列出 `last_verified` 过期的技能/文档，以及该去哪核实。
- **失败降级**：它不会自动改内容，只提醒；核实完手动更新 `last_verified`。

---

## 1. 每日

### 1.1 从领星导数据（每天早上，或隔 1–2 天）

```bash
# 领星后台 → 报表 → 导出：产品表现 / 广告 / FBA 库存（xlsx 或 csv）
python3 scripts/import_lingxing.py ~/Downloads/产品表现.xlsx
python3 scripts/import_lingxing.py ~/Downloads/广告报表.xlsx
python3 scripts/import_lingxing.py ~/Downloads/FBA库存.xlsx
```

- **最小输入**：领星后台导出的原始 Excel/CSV。脚本按表头自动识别表类型；识别不出来会报错并列出它看到的表头，不会硬塞。
- **输出**：原始文件落 `data/raw/<日期>/`（永不修改），归一化结果写 `data/normalized/`（可重算），并在 `data/MANIFEST.md` 记一行（行数、缺字段、quality 状态）。
- **degraded 门禁（已实现）**：脚本把字段分"关键字段"和"可选观察列"（如 `inventory_daily.unit_cost`、`sales_daily.title` 等不参与判定）；**关键字段缺失率 >20%** 才把整表标 `quality: degraded`，相关技能只会给观察不给建议。可选列缺失不报。
- **同日同名防覆盖（已实现）**：`data/raw/<日期>/` 里已有同名文件时，旧文件先移到 `data/raw/<日期>/superseded/`（加时间戳前缀），再放新文件；只增不删。
- **失败降级**：
  - 认不出表头 → 报错并列出看到的表头，用 `--type sales_daily|ads_daily|inventory_daily|sku_master` 显式指定。
  - 读 `.xlsx` 缺 openpyxl → 提示装它，或在领星里另存为 CSV。
- **下一步**：导完跑 0.2 确认新鲜度。

### 1.2 每日经营简报（每天早上看店）

```bash
python3 skills/amz-sku-daily/scripts/run.py
```

- **最小输入**（`data/normalized/`）：
  - 必需：`sales_daily.csv`。缺它只能报数据不足。
  - 可选：`ads_daily.csv`、`inventory_daily.csv`。缺哪张就省略对应事实并明确披露，**不能补写"正常"**。
- **输出**固定四段：
  1. **概览**：销量、销售额、广告花费等原始事实汇总。
  2. **异常**：按相邻两个有数据的日期比对，筛出骤涨/骤跌/零销量后出单的 SKU，以及有花费无单的 campaign。
  3. **待确认**：需要人工归因的事项。
  4. **数据情况**：实际覆盖了哪几张表、缺什么、是否 degraded。
- **它不做**：不直接说"为什么"、不改价、不改竞价、不出利润结论。
- **失败降级**：
  - 只有一个数据日期 → 不计算骤涨骤跌，只报概览。
  - 某 SKU 在相邻日期没记录 → 不当 0，不推断归零。
  - 脚本报错 → 回 0.1 跑 selftest 和阈值测试。
- **下一步**：异常段里的 SKU/campaign 决定今天先深挖哪个；归因（差评/掉排名/竞对降价）必须人工做。

### 1.3 断货预警（每天，或库存紧张时）

```bash
python3 skills/amz-stock-alert/scripts/run.py
```

- **最小输入**：
  - `inventory_daily.csv`：至少含 `asin`/`sku`/`fba_available`。
  - `sales_daily.csv`：必须确实覆盖近 28 天；脚本把输入销量合计 ÷28 当日均销量，**不会替你证明窗口完整**。
- **输出**：三组 SKU 排队——急（<10 天）、关注（<21 天）、候选预警（21–28 天）；每个 SKU 列出 FBA 可售、窗口销量、可售天数。
- **核心公式**（可手工复算）：`days_of_supply = fba_available / (近28天销量 / 28)`。销量为 0 时输出 `None`，不编天数。
- **它不做**：不算全公司库存、不算采购量、不清货降价、**不判定 Amazon 低库存费资格**（官方要长期 90 天 + 短期 30 天双口径，本脚本没有）。
- **失败降级**：
  - 缺库存表 → 报数据不足，不出补货建议。
  - 缺销量表或销量为 0 → 不计算天数，只留库存观察。
  - 输入不是完整 28 天窗口 → 只作相对排序，并在输出里披露窗口不符。
  - 阈值文件读不到 → 用内置占位默认值并显示"未校准"警告，**不把默认值叫公司标准**。
- **下一步（必须人工补）**：本地仓数量、在途批次、供应交期、资金——这些不在表里，人拍板下单量。

### 1.4 广告异常深挖（广告日常监控）

每日简报的【异常】段已经把"有花费无单"的 campaign 列出来了。要深挖：

```bash
# 先确认算式库是好的
python3 skills/_shared/test_metrics.py
```

然后按 `skills/amz-ads-diagnose/SKILL.md` 的五层流程（定目标 → 算盈亏线 → 六格矩阵 → 整体账 → 词根）走。注意：

- **这个技能没有 `scripts/run.py`**，它是一套方法（SOP），由你或 agent 按 `ads_daily.csv` 里的搜索词数据逐步判断。
- **盈亏平衡 ACOS 当前算不出来**——成本未校准，只能看花费/销售/ACOS 绝对值，不给"该不该压到 X%"的结论。
- 否词/降竞价的参数清单可以出，但**后台改竞价是写操作，人去改**。

---

## 2. 每周

### 2.1 Listing 周体检（每周一）

```bash
python3 skills/amz-listing-audit/scripts/run.py
```

- **最小输入**（`data/normalized/`）：
  - 必需：`sku_master.csv`（`sku`/`asin`/`oe_number`/`vehicle_make`/`vehicle_model`/`year_from`/`year_to`/`position`）。缺它体检做不了。
  - 可选：`sales_daily.csv`——用于按销量排"先修谁"；缺它不排优先级。
  - **可选第 5 张手工表：`listing_current.csv`**（见下）。没有它，脚本**只查 fitment 命门**，标题/五点/描述/A+ 整段标"需人工复核"，**不假装查过**。
- **`listing_current.csv` 实际字段**（手工从卖家后台/工具导出，脚本不自动抓）：

  ```csv
  asin,title,bullets_count,description_len,has_a_plus,main_image_path
  B0XXXXXXX,Control Arm for Honda Accord 2015-2018,5,320,1,/path/main.jpg
  ```

  放置路径：`data/normalized/listing_current.csv`。`main_image_path` 指向本地图片文件；脚本只检查路径是否存在，不判断图片合规（图片合规跑 2.2 的 `img_check.py`）。
- **输出**三段：
  1. **【汽配命门】**：OE 号/年款/车型填写率；OE 率 <90% 时警告"适配类分析先别做"。
  2. **【内容项】**：有 `listing_current` 时逐条列标题长度/五点数/描述长度/A+ 有无/主图路径问题；标题命中车标触发词输出 `HOLD`。没有 `listing_current` 时整段交人工。
  3. **【需人工复核】**：五点说服力、A+ 结构、主图白底与占比（跑 2.2）、标题之外的车标扫描。
- **规则**（来源：亚马逊公开 listing 规范的通用长度惯例，未校准）：标题 80–200 字符、五点 ≥5 条、描述 ≥200 字符、OE 号填写率 <90% 时适配类分析只出观察。
- **失败降级**：
  - 缺 `sku_master` → 输出"体检做不了"，给导入指引。
  - 缺 `listing_current` → 只做适配命门，内容项整体标"需人工复核"。
  - OE 填写率 <90% → 适配类分析只出观察不出建议。
  - `main_image_path` 文件不存在 → 列路径，不据此判断图片合规。
- **下一步**：问题清单出来后，改文案/换图是写操作，人去卖家后台改。

### 2.2 Listing 图片检查（做新图或返工老图时）

```bash
# 主图（最严：白底 + 产品占比 + 短边 2000px）
python3 skills/amz-listing-images/scripts/img_check.py path/main.jpg --role main

# 副图
python3 skills/amz-listing-images/scripts/img_check.py path/02.jpg path/03.jpg --role secondary

# 生成适配车型卡（副图/A+ 用，不能当首图）
python3 skills/amz-listing-images/scripts/make_fitment_card.py \
  --product path/product_nobg.png \
  --out path/fitment-01.jpg \
  --fit "2015-2018 Honda Accord" \
  --position "Front Left Lower Control Arm" \
  --oe "51360-TVA-A00"
```

- **最小输入**：图片文件；`make_fitment_card.py` 的车型/年款/OE 号**必须从 `sku_master.csv` 读，不手打**（手打是错图主要来源）。
- **输出**：主图 0 错误才算过；副图允许警告但逐条人工看。
- **硬规则**：主图必须纯白底 RGB(255,255,255)、产品占比 ≥85%、短边 ≥2000px、无透明通道。
- **车标门禁**：图片/文案/Fitment 卡里出现任何车标 → 一律 HOLD，移除或替换并人工复核；正常适配文字（"适用于 Honda Accord"）不阻断。脚本不识别图里的车标，这一步靠人放大车头/车尾/轮毂检查。
- **失败降级**：Pillow/numpy 没装 → `python3 -m pip install --user pillow numpy`；中文字体在某些 macOS 会变豆腐块，第一张图肉眼确认。

### 2.3 竞品周跟踪（默认关）

```bash
# 先确认竞品清单已填
# 编辑 profiles/competitors.md，喂 5–10 个同货架 ASIN
# 然后按 skills/amz-competitor-watch/SKILL.md 走（无 run.py，是方法）
```

- **前置条件**：`profiles/competitors.md` 里有人喂的 ASIN 清单。没清单时这个自动化是 `default: off`，跑了也没意义。
- **它不做**：不抓竞品页面（违反平台条款），只盯人喂的 ASIN 的相对变化。

### 2.4 周日校准（每周日，唯一允许改阈值的地方）

```bash
python3 skills/amz-calibration/scripts/run.py
```

- **最小输入**：`judgements/*.md`（每次诊断产出的判断记录，含 `expected` 和 `review_on`）。
- **输出**：拉上一周所有到期的 open 判断，逐个对账，统计每个技能的命中率（`confirmed / (confirmed + refuted)`）。
- **它做什么**：
  - 命中率 < 50% 的技能 → 默认只出观察不出建议，直到改好。
  - 同一规则被证实 3 次 → 升级为画像事实；被推翻 2 次 → 降权。
  - 阈值修改只允许改 `config/thresholds.yaml`，且每次写进 `config/CHANGELOG.md`（改什么、为什么、依据哪条判断）。
- **它不做**：**不自动改当天的脚本输出**，不形成运行时循环；不自动改画像文件，不自动抓官方页面。
- **失败降级**：没有 judgements 时直接报"本周没有到期判断"，不编命中率。

---

## 3. 每月

### 3.1 月度经营复盘（每月 1 号）

```bash
python3 skills/amz-sku-monthly/scripts/run.py
```

- **最小输入**：`sales_daily.csv`、`ads_daily.csv`、`inventory_daily.csv`（整月）。
- **输出**：四段——【卖什么】（SKU 结构）、【压在哪儿】（有库存但 0 销的滞销 SKU）、【广告花费占销售额】、异常。
- **它不做**：不算毛利率（成本未校准）、不算盈亏平衡 ACOS、不淘汰/加码投放（决策人做）。
- **对照基线**：`config/thresholds.yaml` 里的参考区间可以拿来对比，但**不能拿全年 total_sum 反推本月结构**。
- **失败降级**：数据不够整月 → 只报现有窗口的事实，不给月度结论。

---

## 4. 装定时任务（可选，第二天起）

仓库**不替你装 crontab**，只保证脚本本身是幂等、可重复跑的。自己排：

```cron
40 5 * * *  cd /path/to/amazon-ops-skills && python3 scripts/fetch_lingxing.py --days 3
15 6 * * *  cd /path/to/amazon-ops-skills && python3 skills/amz-store-daily/scripts/run.py
35 6 * * *  cd /path/to/amazon-ops-skills && python3 skills/amz-alert-center/scripts/run.py   # 退出码 1 = 要人看
```

几条经验：

- **先手工跑一周再排**，否则你不知道哪个任务本该失败；
- 预警类任务根据**退出码**决定要不要发通知（0 不打扰、1 叫人、2 补数据）；
- 跑数与出报告分开排：拉数失败不影响昨天的报告；
- 别在笔记本上排每天的任务（合盖就停），放常开的机器。


## 6. 通用失败降级速查

| 症状 | 第一反应 | 第二反应 |
| --- | --- | --- |
| 任何技能输出一堆 `needs_data` | 跑 `python3 scripts/check_data_freshness.py` | 去第 1.1 步补导数据 |
| 脚本报 TypeError / KeyError | 跑 `python3 scripts/selftest.py` | 跑 `python3 skills/_shared/test_thresholds.py` 看阈值 |
| 简报里没有广告段 | 没导 `ads_daily.csv` 或表头没识别对 | 重新导出，或看 `data/MANIFEST.md` 的字段缺失率 |
| 断货预警只出几个 SKU | `sales_daily` 没覆盖近 28 天 | 补齐窗口后再跑；当前结果只能相对排序 |
| Listing 体检全是"适配类分析先别做" | `sku_master` 的 OE 号/年款缺失率 >10% | 先补主数据，不要硬出适配结论 |
| 图片检查主图报白底不通过 | 原图有阴影/渐变 | 去背 → 合成纯白底 → 重跑 |
| 月度复盘没有利润段 | **这是预期的**：成本未校准 | 不要拿领星 total_sum 的毛利数顶替 |

---

## 7. 想追溯任何一个数

| 你想知道 | 去哪 |
| --- | --- |
| 这个字段是什么意思、单位是什么 | `system/DATA-CONTRACT.md` |
| 这个阈值为什么是 21 天、来源是什么 | `config/thresholds.yaml`（每条带 `calibration_status`/来源/时间窗/边界） |
| 这个异常是怎么算出来的 | `skills/_shared/metrics.py`（+ `python3 skills/_shared/test_metrics.py` 看断言数） |
| 这条官方规则/税率/图片规范的出处 | `sources/SOURCES.md` |
| 某次阈值为什么改了 | `config/CHANGELOG.md` |
| 某次报告归档到了哪个云目录 | `python3 scripts/report_index.py current`（按 date/kind/标题查最新 cloud_url）；路由配置见 `config/report_delivery.json` |
