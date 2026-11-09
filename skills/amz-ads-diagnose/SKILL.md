---
name: amz-ads-diagnose
description: 用户明确说广告有问题（ACOS 高/烧钱不出单/要不要加预算）时才用：先定目标再算盈亏线，按 CPC×转化×利润矩阵给处置，只出建议不改竞价。例行巡检看 amz-alert-center 的广告预警即可，不主动跑本技能。
version: 1.0.0
author: Kelin Pan, ZCode
license: private
last_verified: 2026-11-04
review_by: 2027-02-04
platforms: [macos, linux]
metadata:
  automation:
    tags: [亚马逊, 广告, ACOS, 汽配, 复盘]
    related_skills: [amz-sku-daily, amz-stock-alert, amz-calibration]
---

# 亚马逊广告诊断（汽配）

方法本身来自我们自己的手册（`knowledge/amazon/06_运营手册/第八章-亚马逊汽配类广告经验与优化.md`），不是外面抄的。

**两种用法**：
1. **自动巡检（`scripts/run.py`）**：读 `ads_daily`（campaign 级日数据），自动扫「花钱没出单 / ACOS 超线 / 花费骤增」三类异常，出 HTML 报告 + 群消息摘要。每天 07:00 由自动化任务跑。
2. **人工深度诊断**：按本文下面的流程走，对单条 campaign 算盈亏线、出实验卡。脚本只覆盖「今天哪条在烧钱」，不替代深度诊断。

分层边界：广告原始事实（花费/点击/订单/销售额）→ 派生指标（ACOS、贡献毛利、可售天数）→ 未校准候选规则（阈值全部来自 `config/thresholds.yaml` 的 `ads` 段）→ 处置建议（继续/降价/加预算/否词/停）→ 人工审批后才落地（本技能不碰竞价、预算、Listing）。


## 交互协议（主动调用时：先问清，再执行）

本技能是**主动式**技能。被调用时不要直接闷头跑脚本：先核对下面的前置信息，
缺哪项就**用带选项的问题**一次问清（一次最多 3 个问题，能合并就合并），拿到答案再执行。

| 前置信息 | 为什么需要 | 选项 / 默认值 |
|---|---|---|
| 店铺范围 | 多店数据结构不同 | 选项：全部多店（默认）/ shop_a / shop_b / shop_c |
| 时间窗 | 异常判定依赖窗口 | 选项：昨日（默认）/ 近 7 天 / 近 30 天 |
| 诊断级别 | 活动级还是 ASIN/SKU 级 | 选项：两级都要（默认）/ 仅活动级 / 仅 ASIN 级 |
| 阈值口径 | 高花费 0 单、ACOS 红线 | 默认读 config/alert_rules.json + targets.json；用户可临时改，改前复述 |

多轮对话规则：
1. 用户后续补充或修改口径时，以**最新一轮**为准，并复述确认关键参数（范围/对象/阈值）。
2. 信息齐全后先用一句话复述「我要用什么对象 + 什么时间窗 + 什么阈值 + 输出什么」，再动手。
3. 缺数据/缺密钥时直说并给替代路径，**不编数**；外部写操作（发消息、写外部表格、改广告）必须显式确认。
4. 用户只想快速要结果时，可直接采用上表默认值，但要在开头列出所用默认值。

---


## 自动巡检脚本（scripts/run.py）

```bash
# 在仓库根目录执行；用 install_skills.py 软链安装的，把 skills/ 换成 ~/.agents/skills/ 下的实际路径
# 先拉 campaign 级日数据（增量，已有的日期跳过）
python3 scripts/fetch_ads.py --days 7

# 扫异常（HTML 报告 + 摘要）
python3 skills/amz-ads-diagnose/scripts/run.py

# 群消息摘要
python3 skills/amz-ads-diagnose/scripts/run.py --format text
```

**判什么**（三件套，顺序不能反）：

| 顺序 | 信号 | 条件 | 级别 | 为什么排这个顺序 |
| --- | --- | --- | --- | --- |
| 1 | 烧钱 | 花费 ≥$15 且 0 单 且点击 ≥8 | critical | 真金白银在烧，最急 |
| 2 | ACOS 超线 | 有单 且 ACOS ≥25%（≥18% 报 high） | critical/high | 有单说明词是对的，只是效率差 |
| 3 | 花费骤增 | 今日 ≥ 昨日 2 倍且 ≥$30 | high | 预算被放大或竞价被抬 |

**为什么不只看 ACOS**：1 单变 2 单 ACOS 就砍半，样本太小时绝对值没有意义。所以先看有没有烧钱，再看效率。

**ACOS 阈值**：18% 算高、25% 要动手（在 `config/targets.json` 的 `acos_ceiling` 与 `config/thresholds.yaml` 的 ads 段改）。
成本结构未校准，ACOS 只能横向比效率，**不能当盈亏结论**。

## 用途

对单个 campaign / ad group / 搜索词做广告诊断：先明确这轮广告的目标，再用成本结构算盈亏平衡 ACOS，按 CPC×转化×利润给出处置建议，并把每条结论写成带预期和复核日的实验卡。它回答"这条广告该怎么办、依据是什么"，不直接改任何广告设置。

## 何时使用 / 不使用

**使用：**

- 每日巡检（`amz-sku-daily`）发现某 campaign ACOS 异常 / 有花费无单。
- 每周复盘：本周改了什么、数据有没有动。
- 有人问"这个广告要不要关 / 加预算 / 降价 / 否某个词"。

**不使用：**

- 不直接改竞价、改预算、改 Listing——四态机里永远停在 `DIAGNOSE` 或 `DRAFT`，不进 `RELEASE_PREP` / `APPROVED_WRITE`。
- 不用单日数据下结论：判断窗口最短 7 天（`ads.min_days_window`），大促前后单独看。
- 不拿 ACOS 绝对值跟同行或跟自己不同成本结构的 SKU 比：盈亏线差一倍，比了没用。
- 不用它判定"广告变差"——低库存会限流，先看 `amz-stock-alert` 的可售天数。

## 最小输入

- `data/normalized/ads_daily.csv`（领星广告日报/小时报导出后归一化）：字段见 `system/DATA-CONTRACT.md` 的 `ads_daily`。
- 每个被诊断 SKU 的**成本结构**：拿货、头程、FBA 配送费、佣金率、退货损耗率、售价。没有它就算不出盈亏线，只能看 ACOS 绝对值——那是不够的。
- 规则：`config/thresholds.yaml` 的 `ads` 段（`acos_tolerance_over_breakeven=0.15`、`high_spend_no_order=15.0`、`min_days_window=7`，全部未校准）。
- 共享算式库 `skills/_shared/metrics.py`（`breakeven_acos()`、`evaluate_ads()`、`decide_term()`；`python3 skills/_shared/test_metrics.py` 应全绿）。

## 运行与输出

本技能**没有 `scripts/run.py`**：按下面"高级规则"的流程走，算式统一调 `skills/_shared/metrics.py`，不手算。

```bash
# 算式库自测；广告输入表不在时不会有任何脚本替你拉数
python3 skills/_shared/test_metrics.py
```

输出固定为五段（方便对账）：

```
【结论】一句话：这条广告该做什么（继续 / 降价 / 加预算 / 否词 / 停 / 先查库存）
【依据】盈亏线 X% ｜ 当前 ACOS Y% ｜ 近 7 天花费/销售额/订单 ｜ 矩阵位置
【动作】最多三条，每条带对象和幅度（例：否掉 "for 2016 camry" phrase，预计省 $12/周）
【实验卡】改什么、预期结果、复核日期（默认改后 14 天）
【不确定】哪些数没拿到（没成本结构 / 缺 7 天数据 / 库存断档）
```

派生指标与规则的区别：ACOS、贡献毛利是派生指标；"高于盈亏线 15% 以内算波动"是候选规则（阈值未校准）；最后落到动作时必须带对象和幅度。

## 示例

```bash
# 公式来自 metrics.py，不要手算盈亏线：
python3 - <<'PY'
from skills._shared import metrics
print(metrics.breakeven_acos(price=30.0, unit_cost=12.5, freight=2.0,
                             fba_fee=4.5, commission_rate=0.15))
PY
```

对一条 `<campaign>`：用近 7 天 `ads_daily` 行的 spend/sales/orders 算 ACOS，跟该 SKU 的 `breakeven_acos()` 比；搜索词逐词用 `decide_term()` 判 keep/watch/negative/pool。没有真实成本结构时，输出里只能写"盈亏线未知，仅列 ACOS 趋势"，不得编一个百分比。

## 失败降级

- 缺成本结构：算不出盈亏线 → 输出 `needs_human_review`，只报 ACOS 绝对值和花费，不下"赚/亏/关"的结论。
- `ads_daily` 缺表或不足 7 天：标注数据窗不够，只出观察，不出处置建议。
- 某搜索词点击样本不足（`MIN_CLICKS_FOR_JUDGEMENT=8`，词根 `ROOT_MIN_CLICKS_FOR_JUDGEMENT=12`）：按 `decide_term()` 继承词根或进长尾池 `pool`——`pool` 是一种决策，不是未决。
- 阈值文件读不到：`metrics.load_thresholds()` 用内置占位默认值并打未校准警告；不得把默认值称为公司标准。
- 库存可售天数低（<28 天候选线）：把"广告变差"降级为"先查库存"，不写广告结论。

## 数据质量限制

- **盈亏线依赖的成本结构尚未校准**：领星导出的毛利/成本是未校准参考，不得当准确事实写进结论，也不得写死成阈值。没有用户提供的真实成本时，盈亏线一律标"未校准/未知"。
- **ACOS 低于盈亏线不等于广告赚钱**：可能是自然单占比高；高于盈亏线也不一定要关（见高级规则"整体账"）。
- 判断窗口 ≥7 天；自然单占比、退货、大促、站外单造成的波动需要人工剔除或解释。
- 阈值（15% 容忍、$15 高花费无单、7 天窗）都是未校准占位值，不是公司标准。
- 本技能只读，不碰领星。

## 人工确认边界

- 脚本/流程只生成诊断和实验卡。改竞价、改预算、否词、停广告、改 Listing 都必须由人审批后在广告后台执行；本技能不自动写任何外部动作。
- 每条结论必须能指回一次取数（日期 + 报表名）和成本依据，不是拍的。
- 一张实验卡只改一个变量（出价/预算/否词/Listing 四选一），到期由 `amz-calibration` 拉出来对账。
- 广告素材文案或图里若出现车标触发词（用 `metrics.brand_logo_hold()` 扫文案），命中即 `HOLD`，移除/替换并复核前不得发布；正常车型适配文字（"Fits 2015-2018 Accord"）不因该规则自动阻断。

## 追溯与验证

- 数据契约：`system/DATA-CONTRACT.md`（`ads_daily` 字段）
- 阈值来源与边界：`config/thresholds.yaml`（`ads` 段）、`config/CHANGELOG.md`
- 公式与决策：`skills/_shared/metrics.py`（`breakeven_acos`、`evaluate_ads`、`decide_term`、`brand_logo_hold`）
- 手册方法：`knowledge/amazon/06_运营手册/第八章-亚马逊汽配类广告经验与优化.md`
- 任务映射见 `docs/WORKFLOWS.md`
- 验证：`python3 skills/_shared/test_metrics.py`、`python3 scripts/selftest.py`；每条结论的盈亏线应能回到成本结构手算，实验卡有复核日期。

## 高级规则

### 第一闸门：先问目标（不问目标不下结论）

这轮广告是：测试新品 / 防守排名 / 品牌获客 / 推自然排名 / 成熟品要利润？五种目标下 ACOS 的地位完全不同。他说"把 ACOS 降下来"时，先确认降 ACOS 会不会伤到这轮主目标。

### 第二闸门：算盈亏线，不拿绝对值比

```
盈亏平衡 ACOS = (售价 − 拿货 − 头程 − FBA − 佣金 − 退货损耗) / 售价
```

用 `metrics.breakeven_acos()` 算，别手算。**ACOS 低于盈亏线不等于广告赚钱**（可能是自然单占比高），高于也不一定要关（见第四条）。

### 第三层：CPC × 转化 × 利润 六格矩阵（手册原表）

| CPC | 转化 | 利润 | 处置 |
| --- | --- | --- | --- |
| 高 | 高 | 任意 | 打爆款，抢自然流量 |
| 高 | 差 | 高 | 保守广告，靠广告盈利（精品） |
| 高 | 差 | 低 | 清库存 |
| 低 | 高 | 任意 | 加大投放，随便都赚 |
| 低 | 差 | 高 | 保守广告（精品） |
| 低 | 差 | 低 | 清库存 |

### 第四层：整体账，不看单条

- 手册明确：**广告单独亏损但整体订单为正时，应维持**（例：某 SKU 长期 ACOS 100+，但广告撑住关键词排名，自然单把整体做正）。
- 判断窗口 ≥7 天，不许拿单日数据否定一条广告。
- 低库存会限流：库存低于 28 天销量时 CPC 抬升、转化下滑，**这时候的"广告变差"其实是库存问题**，先看 `amz-stock-alert`。

### 第五层：词根，解决汽配的长尾问题

汽配搜索词组合单一但车型词组极多（`front control arm for 2015 honda accord`）。

- 单词点击不足时继承**词根**（`front control arm`，由 `metrics.keyword_root()` 压出）的决策；
- 词和词根都不足 → 进长尾池汇总监控（这是决策，不是未决）；
- 否词优先给 phrase 级（一条 phrase 顶几十条 exact）。

### 复盘怎么做

- **周复盘**：上周所有实验卡 → 拉真实数据对账 → 记 `confirmed` / `refuted` → 命中率进 `judgements/`。
- **月复盘**：看结构而不是单条——广告占比（SP/SD/SB）、自动/精准/广泛的预算分布、否词数量增长、整体 ACOS 与自然单占比（具体结构归 `amz-sku-monthly`）。
- 每次结论都写进 `judgements/<日期>-ads.md`，字段：id / skill / status / expected / review_on（格式见 `system/ARCHITECTURE.md`）。

### Pitfalls

- **拿 ACOS 绝对值比同行**：不同成本结构下盈亏线差一倍，比了没用。
- **单日数据下结论**：至少 7 天；大促前后单独看。
- **把库存限流当广告问题**：先查可售天数。
- **改多个变量**：一张实验卡只改一个（出价/预算/否词/Listing 四选一）。
- **只说"优化一下"**：必须给对象+幅度+预期，否则没法对账。
