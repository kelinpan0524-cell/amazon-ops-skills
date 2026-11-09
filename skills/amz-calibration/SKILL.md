---
name: amz-calibration
description: 每周日校准技能命中率时用：把到期判断拉出来对账，算命中率，低了就降权。用户不会主动提这件事，只在定时校准任务里跑。
version: 1.0.0
author: Kelin Pan, ZCode
license: private
last_verified: 2026-11-04
review_by: 2027-02-04
platforms: [macos, linux]
metadata:
  automation:
    tags: [亚马逊, 复盘, 自迭代]
    related_skills: [amz-ads-diagnose, amz-sku-monthly]
---

# 每周校准（自迭代的核心）

这是整个仓库唯一被授权**讨论**阈值改动的地方。但它本身不改任何文件：对账取数、把判断标成 confirmed/refuted、改 `config/thresholds.yaml` 都由人（或人授权的 agent）手动完成。别的技能只能读阈值，不能改。

分层边界：历史判断记录（`judgements/*.md`）→ 派生命中率（confirmed / (confirmed+refuted)）→ 候选处置建议（降权 / 沉淀 / 调阈值）→ 人工执行写回。脚本只列清单和统计，不取数、不写状态、不改阈值。

## 用途

每周把到期该复核的判断列出来，统计每个技能的历史命中率，并对"命中率过低建议降为只观察不建议""连续证实可沉淀为画像事实""该调哪个阈值"给出**建议**。它是自迭代的对账入口，不是自动改数的闭环。

## 何时使用 / 不使用

**使用：**

- 每周日 20:00 定时跑，拉出本周到期的判断。
- 有人说"这个技能最近老说错"，需要用命中率而不是感觉来判断。

**不使用：**

- 不用于自动修改 `judgements/*.md` 的 status，也不用于自动改 `config/thresholds.yaml`——这些必须人来写回。
- 不替你去领星拉数核对：脚本取不到真实数据，对账那一步必须人/agent 真去拉数。
- 不用于单次诊断出结论——单次诊断归各业务技能。
- 不让任何技能（包括本技能）运行时读自己的命中率并自动调阈值：那会形成循环依赖，禁止。

## 最小输入

- `judgements/*.md`：每次诊断的结论，带 frontmatter（`id` / `skill` / `status` / `expected` / `review_on`），格式见 `system/ARCHITECTURE.md`。目录不存在时脚本会提示先建判断记录。
- `config/thresholds.yaml` 的 `calibration` 段：`confirm_hits_to_promote=3`、`refutes_to_demote=2`、`min_hit_rate=0.50`（机制参数，`calibration_status: 不适用`）。
- 可选环境变量：`AMZ_JUDGE_DIR` 指向判断目录（自测时用）。

## 运行与输出

```bash
# 在仓库根目录执行；用 install_skills.py 软链安装的，把 skills/ 换成 ~/.agents/skills/ 下的实际路径
python3 skills/amz-calibration/scripts/run.py
```

输出三块：

1. **【到期待复核】**：所有 `status: open` 且 `review_on ≤ 今天` 的判断（id / skill / 到期日 / 预期）。
2. **【命中率】**：按技能统计 confirmed/refuted/open 与命中率；低于 `min_hit_rate` 标"建议降为只观察不建议"，confirmed ≥ `confirm_hits_to_promote` 标"可沉淀为画像事实"。
3. **【阈值】**：固定提示"改动只能改 `config/thresholds.yaml`，并在 `config/CHANGELOG.md` 记一行"。

派生指标（命中率）与规则（降权/沉淀）的区别：命中率是纯计数；降权与沉淀是需要人执行的建议。

## 示例

```bash
# 合成数据自测（AMZ_JUDGE_DIR 指临时目录）
python3 scripts/selftest.py
# 真实跑（judgements/ 已积累判断后）
python3 skills/amz-calibration/scripts/run.py
```

对任一条到期判断，人工对账后在原文件里把 `status` 改成 `confirmed`（写一句实测值）或 `refuted`（写清是假设错还是执行没到位）。示例模板：

```
---
id: J-YYYYMMDD-01
skill: amz-ads-diagnose
status: open
expected: "否掉高花费词后花费降 20%"
review_on: 2026-11-18
---
```

## 失败降级

- `judgements/` 不存在或为空：输出"还没有判断记录"并给模板，不出命中率，不编造历史。
- 判断文件没有 frontmatter / 缺 `status` / 缺 `review_on`：脚本按默认 `open` 与远期到期日处理，统计可能不准；人应补全字段。
- 某技能只有 open 没有已结案判断：标"未结案 N 条"，不算命中率。
- 阈值文件读不到：用内置占位默认值并打未校准警告（`metrics.load_thresholds()`）。

## 数据质量限制

- 命中率只反映**已结案**判断；open 判断再多也不参与命中率。
- 命中率低可能是样本少（刚结案几条），不必然代表技能失效；脚本不自动降权，只给建议。
- 被推翻的判断必须保留（只增不删，过期标 `outdated`），不能只记成功。
- 机制参数（3/2/50%）是自迭代规则，与经营数据无关，不存在"未校准"一说，但改动仍要走 CHANGELOG。

## 人工确认边界

- 脚本不写任何文件。把 `status` 改成 confirmed/refuted、改阈值、写画像，全由人执行并留痕。
- **阈值改动**：只允许人手动改 `config/thresholds.yaml`，并在 `config/CHANGELOG.md` 记一行（改什么、为什么、依据哪条判断）。技能不得在运行时自动改阈值，也不得由本脚本直接写配置。
- 一次只调一个阈值、看一轮，否则分不清是哪个起的作用。
- 沉淀进 `profiles/*.md` 的事实必须带 source/evidence，格式见 `system/ARCHITECTURE.md`。

## 追溯与验证

- 判断格式：`system/ARCHITECTURE.md`
- 阈值与改动留痕：`config/thresholds.yaml`、`config/CHANGELOG.md`
- 脚本：`skills/amz-calibration/scripts/run.py`
- 阈值读取：`skills/_shared/metrics.py`（`load_thresholds`）
- 任务映射见 `docs/WORKFLOWS.md`
- 验证：`python3 scripts/selftest.py`；每条结案判断都应能指回一次取数与实测值，不是"感觉"；阈值改动能追到依据的判断 id。

## 高级规则

### Procedure

1. 脚本列出所有到期该复核的判断。
2. **逐条用真实数据核对**（这一步必须人/agent 真去拉数，脚本替不了）：
   - 预期达成 → 文件里 `status: confirmed`，写一句实测值。
   - 没达成 → `status: refuted`，写清是假设错还是执行没到位。
3. 看命中率：低于 50% 的技能，下次只出观察不出建议，直到改好。
4. 被证实 ≥3 次的结论，摘成一行写进对应画像（`profiles/*.md`），标来源。
5. 要调阈值 → 改 `config/thresholds.yaml` + 在 `config/CHANGELOG.md` 记一行（改什么、为什么、依据哪条判断）。

### Pitfalls

- **自己判自己没错**：不能用"我觉得改对了"当证据，必须有数。
- **只记成功不记失败**：被推翻的判断更要留，那才是学习的来源。
- **一次改多个阈值**：改一个、看一轮，否则分不清是哪个起的作用。
