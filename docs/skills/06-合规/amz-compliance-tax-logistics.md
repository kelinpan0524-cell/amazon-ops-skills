# amz-compliance-tax-logistics

> 汽配跨境合规、税务、IP、清关、HS 编码、履约与库存风险门禁。用于判断"这个 SKU 能不能卖/能不能发/能不能入 FBA"，覆盖禁限售、认证标签、VAT/GST/Sales Tax/Nexus、Marketplace Facilitator、HS/关税/DDP-DDU、FBA/FBM/海外仓/3PL、危险品、文件对账。source-first：没有官方一手证据时一律标 unverified / needs_data，不给最终法律/税务/清关结论。

| | |
| --- | --- |
| 类型 | 合规门禁 |
| 运行 | 需要时手动 |
| 有脚本 | 否（流程型，AI 按 SKILL.md 编排） |

## 数据源

官方一手证据优先（source-first）

## 逻辑链路（这是怎么算出来的）

① 判断能不能卖/能不能发/能不能入 FBA：禁限售/认证标签/VAT-GST/Nexus/HS 编码/DDP-DDU

② 没有官方证据一律标 unverified / needs_data——不给最终法律税务结论

## 为什么这样设计 / 阈值依据

source-first：合规结论没有官方一手证据就标 unverified——错误的『通过』比『不知道』危险得多。

## 输出去向

门禁结论（unverified 不算通过）

---

本文档由 `scripts/gen_skills_kb.py` 生成；深度分析改脚本里的 KB 数据，描述/用法看 `skills/amz-compliance-tax-logistics/SKILL.md`。