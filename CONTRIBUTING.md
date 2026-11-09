# 开发约定

改这个仓库之前先读这一页。规则不多，但都是踩过坑定下来的。

## 加一个技能

```
skills/amz-your-skill/
  SKILL.md          # 必填
  scripts/run.py    # 可选（纯方法论技能可以没有）
  references/*.md   # 可选：长参考资料，正文按需读
```

`SKILL.md` 的 frontmatter：

```yaml
---
name: amz-your-skill              # 必须和目录名一致
description: 一句话说清「什么时候用我 + 不什么时候用」  # ≤250 字，触发词放句首
when_to_use: （可选）和相似技能区分开的一句话
license: MIT
metadata:
  automation:
    tags: [亚马逊, ...]
    related_skills: [amz-xxx]
---
```

**描述是第一位的**：模型就是靠它决定调不调你。写清三件事：
1. 用户说什么话时该用我；
2. 什么情况下**不要**用我（并指向该用的那个技能）；
3. 用我会得到什么、需要什么前置条件。

## 退出码（全仓统一）

| 码 | 含义 |
| --- | --- |
| 0 | 成功，无需处理 |
| 1 | 成功，但有 critical/high 要人看 |
| 2 | 数据缺失 / 前置条件不满足（没拉数、清单为空、没配密钥） |
| 3+ | 程序错误 |

定时任务靠这个判断"要不要叫人"，所以**不能把失败返回 0**。

## 纯标准库

脚本只用 Python 标准库。确实需要第三方（如 `openpyxl` 读 xlsx）时，做成可选依赖并在文档里标明，
不能让它成为默认路径的硬依赖。CI 跑在裸环境里，就是为了守住这条。

## 缺数据不许编

- 缺表 → 打印"没有 X 数据，先跑 Y"，退出码 2；
- 缺行 → 图上断开，不画 0；
- 字段缺失 → 显示 `—` 或"未设定"，不填占位值。

## 测试

每个技能的 `scripts/` 下可以有 `test_*.py`，`scripts/selftest.py` 会自动发现并执行。

```bash
python3 scripts/selftest.py        # 单元测试 + 技能冒烟 + 报告内容 + 文档链接 + 排版
python3 scripts/ci_check.py        # 架构约束（frontmatter、SKU 列、USD 口径…）
```

新增行为要配一条**在改动前会失败**的测试。

## 隐私边界

- 真实店铺配置、经营数据、密钥**永远不进仓库**；
- 新增配置一律走 `*.example.json` 模板；
- 提交前 `python3 scripts/public_boundary_check.py` 必须通过；
- 报告里不写死任何公司名、店名、人员姓名（CI 会挡）。
