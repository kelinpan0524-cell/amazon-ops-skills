---
name: amz-listing-audit
description: 用户明确要体检某个 listing 时才用：先查 OE 号与年款适配，再查标题/五点/主图，缺项标「待补」。日常巡检不主动触发；图片合规用 amz-listing-images。
version: 1.0.0
author: Kelin Pan, ZCode
license: private
last_verified: 2026-11-04
review_by: 2027-05-04
platforms: [macos, linux]
metadata:
  automation:
    tags: [亚马逊, listing, 汽配, fitment]
    related_skills: [amz-listing-images, amz-ads-diagnose]
---

# Listing 体检（汽配优先查适配）

汽配的 listing 死于适配不清，不是死于形容词不够。所以第一步永远查 fitment，第二步才看文案。

分层边界：主数据与 Listing 事实（OE 号/年款/标题长度/五点数/主图路径）→ 派生覆盖率（OE 填写率、标题字符数）→ 候选规则（`config/thresholds.yaml` 的 `listing`/`fitment` 段）→ 体检问题清单 → 人工复核与发布审批。脚本只标问题，不发布、不改 Listing。


## 交互协议（主动调用时：先问清，再执行）

本技能是**主动式**技能。被调用时不要直接闷头跑脚本：先核对下面的前置信息，
缺哪项就**用带选项的问题**一次问清（一次最多 3 个问题，能合并就合并），拿到答案再执行。

| 前置信息 | 为什么需要 | 选项 / 默认值 |
|---|---|---|
| ASIN / SKU 清单 | 审核必须有对象，无清单不可跑 | 必填；若用户只说「帮我看看 listing」，先追问清单或提供「按销量 Top10」选项 |
| 审核维度 | 不同维度调用不同检查器 | 多选：标题与五点 / 关键词覆盖 / 图片合规 / 违禁词与合规 / 价格与跟卖；默认全选 |
| 站点 | 语言与合规规则不同 | 默认美国站 |
| 输出与严重度 | 结果怎么用 | 默认：HTML 报告 + 按 严重/建议/可选 分级；是否发群需显式确认 |

多轮对话规则：
1. 用户后续补充或修改口径时，以**最新一轮**为准，并复述确认关键参数（范围/对象/阈值）。
2. 信息齐全后先用一句话复述「我要用什么对象 + 什么时间窗 + 什么阈值 + 输出什么」，再动手。
3. 缺数据/缺密钥时直说并给替代路径，**不编数**；外部写操作（发消息、写外部表格、改广告）必须显式确认。
4. 用户只想快速要结果时，可直接采用上表默认值，但要在开头列出所用默认值。

---


## 用途

对输入的 SKU/Listing 做每周体检：先算汽配命门（OE 号、年款区间、车型填写率），再在有 `listing_current` 时自动查标题长度、五点数量、描述长度、A+ 有无、主图路径是否存在，并对标题文字做车标硬阻断扫描。判不了的项（五点说服力、A+ 结构、图片本身）一律标"需人工复核"，不假装通过。

## 何时使用 / 不使用

**使用：**

- 每周一固定跑。
- 新品上架后、老品流量下滑时。
- 需要先确定"先修哪个 ASIN"——脚本按销量排序给出前 5 优先修清单。

**不使用：**

- 不用于直接改 Listing、改标题、改图片——只出问题清单和人工复核项。
- 不用于判断五点写得对不对、A+ 有没有说服力：这些脚本判不了，必须人工。
- 不用于主图白底/占比/像素的技术验收：那是 `skills/amz-listing-images/scripts/img_check.py` 的职责。
- 不用它给"可发布"结论：标题扫描通过 ≠ 整 Listing 通过（见人工确认边界）。

## 最小输入

- 必需：`data/normalized/sku_master.csv`（`sku`/`asin`/`oe_number`/`vehicle_make`/`vehicle_model`/`year_from`/`year_to`/`position`）。缺它体检做不了。
- 可选：`data/normalized/sales_daily.csv`——用于按销量排"先修谁"；缺它就不排优先级。
- 可选：`data/normalized/listing_current.csv`（`asin`/`title`/`bullets_count`/`description_len`/`has_a_plus`/`main_image_path`）。缺它只做适配命门，内容项交人工。
- 规则：`config/thresholds.yaml` 的 `listing` 段（标题/五点/描述/主图长度）与 `fitment` 段（`min_oe_ratio=0.90`、`min_year_ratio=0.90`，均未校准）。
- 图片合规另用：`skills/amz-listing-images/scripts/img_check.py`。

字段口径与覆盖限制见 `system/DATA-CONTRACT.md`。

## 运行与输出

```bash
# 在仓库根目录执行；用 install_skills.py 软链安装的，把 skills/ 换成 ~/.agents/skills/ 下的实际路径
python3 skills/amz-listing-audit/scripts/run.py
```

输出三段：

1. **【汽配命门】**：OE 号/年款/车型填写率与总 SKU 数；OE 率低于 90% 时警告"适配类分析先别做，补数据"，并列出最多 10 个缺 OE 号的示例 SKU。有 `sales_daily` 时按销量列前 5 优先修。
2. **【内容项】**：有 `listing_current` 时，逐条列标题长度/五点数/描述长度/A+ 有无/主图路径问题；标题命中车标触发词时输出 `HOLD <asin>：……移除/替换并复核前不得发布`。
3. **【需人工复核】**：五点说服力、A+ 结构、主图白底与产品占比（跑 `img_check.py`）、以及标题之外的车标扫描。

派生指标（填写率、字符数）与规则（<90% 停适配、HOLD）的区别：脚本只比阈值，不判断关键词质量或文案好坏。

## 示例

```bash
# 先用合成数据验证脚本，再接真实归一化表
python3 scripts/selftest.py
python3 skills/amz-listing-audit/scripts/run.py
```

对输出的任一 `<asin>`，应能回到 `sku_master` / `listing_current` 对应行复算填写率与字符数。主图合规改跑：

```bash
python3 skills/amz-listing-images/scripts/img_check.py path/main.jpg --role main
```

## 失败降级

- 缺 `sku_master`：输出"体检做不了"，给下一步导入指引，不出任何 Listing 结论。
- 缺 `listing_current`：只做适配命门，内容项整体标"需人工复核"，不假装查过标题/五点。
- OE 填写率 < 90%：适配类分析（适配图、适配文案）只出观察不出建议，先补主数据。
- `main_image_path` 指向的文件不存在：列路径，不据此判断图片合规与否。
- 阈值文件读不到：用内置占位默认值并打未校准警告（`metrics.load_thresholds()`）。

## 数据质量限制

- 填写率只反映输入 `sku_master` 的完整度，不代表线上 Listing 真实状态；`listing_current` 是快照，需按 `system/FRESHNESS.md` 关注新鲜度。
- 字符数阈值（标题 80–200、五点 ≥5 条、描述 ≥200 字符）是未校准的通用惯例，只筛明显偏离，不判断关键词质量。
- **车标自动扫描只覆盖 `title` 文字**：五点、描述正文、A+ 与所有图片未接入自动扫描；图像侧仓库没有可靠识别能力。
- 涉及利润/库存结论时另见对应技能；本技能不输出毛利或全量库存。

## 人工确认边界

- 脚本只出问题清单。改标题、改五点、换主图、补主数据、任何发布动作都由人批准。
- **车标硬阻断（全部汽配类目）**：标题文字命中触发词即 `HOLD`，必须移除/替换并复核，不得给可发布结论。**标题之外（五点/描述/A+/全部图片）在人工逐张确认无车标（含方向盘/轮毂中心徽标）前一律保持 HOLD**，不得因标题扫描通过就认为整 Listing 通过。正常 YMM/OE/品牌适配文字（"Fits 2015-2018 Accord"）不因该规则自动阻断，仍走既有商标证据审核。
- 五点说服力、A+ 结构、主图白底/占比/像素：人工或 `img_check.py` 验收，本技能不假装检查过。

## 追溯与验证

- 数据契约：`system/DATA-CONTRACT.md`（`sku_master`、`listing_current` 字段）
- 阈值来源与边界：`config/thresholds.yaml`（`listing`、`fitment` 段）、`config/CHANGELOG.md`
- 公式与车标扫描：`skills/_shared/metrics.py`（`brand_logo_hold`）、本技能 `scripts/run.py`
- 图片验收：`skills/amz-listing-images/scripts/img_check.py`
- 任务映射见 `docs/WORKFLOWS.md`
- 验证：`python3 scripts/selftest.py`；OE 覆盖率数字可复算（行数 ÷ 总行数），每条问题能指到某个 ASIN 的具体字段。

## 高级规则

### Procedure

1. 先看 OE 号/年款/车型填写率，低于 90% 就停在这里补数据——适配不清楚，后面写什么都没用。
2. 有 `listing_current` 就自动查标题长度、五点数量、描述长度、A+ 有无、主图是否存在。
3. 主图跑 `img_check.py --role main`，不合规直接列出来。
4. 按销量排序，先修卖得动的（销量前 5 优先）。
5. 判不了的（五点说服力、A+ 结构）明确写"需人工复核"，不假装检查过。

### Pitfalls

- **别用卖家自己的话判断适配**：以 OE 号和年款区间为准，宣传语不算。
- **标题堆关键词不解决适配**：适配信息缺失时，先补结构化字段。
- **A+ 与主图是两套规则**：主图纯白底，A+ 可以带场景和文字。
