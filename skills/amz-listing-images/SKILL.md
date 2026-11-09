---
name: amz-listing-images
description: 用户要做/要改 listing 图时才用：主图白底、尺寸与占比像素校验、副图检查、适配车型卡（只出 DRAFT）。脚本只能判像素、没有车标识别能力，技术通过仍须人工车标复核，不代表可发布。
version: 1.1.0
author: Kelin Pan, ZCode
license: private
last_verified: 2026-11-04
review_by: 2027-05-04
platforms: [macos, linux]
metadata:
  automation:
    tags: [亚马逊, listing, 图片, 汽配, fitment, 合规]
    related_skills: [amz-listing-audit, amz-compliance-tax-logistics]
---

# 亚马逊 listing 图（汽配）

做图不是难点，**验收**是难点。这个技能的脚本只能判像素事实（白底、尺寸、产品占比、透明通道、边带），**不能识别图里的文字、水印、车标或竞品 logo**。因此任何“技术通过”都只是必要条件，不是可发布结论。

分层边界：像素事实（白底占比/尺寸/占比/透明通道）→ 技术通过或报错 → **不等于发布结论** → 人工逐张复核车标/文字/水印 → 人工审批 → 发布上传（仓库不执行）。

适用范围：**全部汽配类目**。控制臂、衬套、悬置、球头、拉杆只是当前主营示例，不构成适用边界；细长件的占比判定用“长边跨度”而非面积，就是为覆盖这类零件设计的。


## 交互协议（主动调用时：先问清，再执行）

本技能是**主动式**技能。被调用时不要直接闷头跑脚本：先核对下面的前置信息，
缺哪项就**用带选项的问题**一次问清（一次最多 3 个问题，能合并就合并），拿到答案再执行。

| 前置信息 | 为什么需要 | 选项 / 默认值 |
|---|---|---|
| ASIN 与素材 | 做图必须有对象与原图 | 必填；无原图时先确认是否允许用现有素材库 |
| 图片类型与风格 | 主图/A+/场景图规范不同 | 选项：主图（白底合规）/ 场景图 / A+ 模块；默认主图+场景 |

多轮对话规则：
1. 用户后续补充或修改口径时，以**最新一轮**为准，并复述确认关键参数（范围/对象/阈值）。
2. 信息齐全后先用一句话复述「我要用什么对象 + 什么时间窗 + 什么阈值 + 输出什么」，再动手。
3. 缺数据/缺密钥时直说并给替代路径，**不编数**；外部写操作（发消息、写外部表格、改广告）必须显式确认。
4. 用户只想快速要结果时，可直接采用上表默认值，但要在开头列出所用默认值。

---


## 用途

- 对亚马逊汽配 listing 的主图、副图跑像素级合规检查（`img_check.py`）。
- 生成副图/A+ 用的「适配车型」卡（`make_fitment_card.py`），输出仅为 **DRAFT 草稿**，不能当首图。
- 把“图合不合规”从主观“我看着还行”变成可复算的像素检查；但车标、文字、水印、竞品标识这类语义问题，脚本一律交给人工。

## 何时使用 / 不使用

**使用：**

- 新品上架要出主图 + 3–6 张副图，或老 listing 图被压制/被投诉要返工。
- 需要出「适配车型」卡（Fits 2015-2018 Accord 这类）或 A+ 配图。

**不使用：**

- 不做品牌 VI 设计、广告素材（另一套规则）。
- **不做车标/文字/水印的自动识别**：脚本没有视觉/OCR 能力，别把“技术通过”当“图干净”。
- 不做图片版权判断，不替人改竞品图，也不执行任何上传/发布。
- 不替代人工在放大图上逐张检查车头/车尾/轮毂中心/方向盘徽标。

## 最小输入

- 运行依赖：Python 3 + Pillow + numpy（先 `python3 -c "import PIL, numpy"` 确认可用）。
- 去背景可选：`rembg`（开源 MIT；`pip install rembg` 后 `rembg i in.jpg out.png`）。
- `img_check.py`：一张或多张图片路径 + `--role main|secondary`。
- `make_fitment_card.py`：`--product`（去背 PNG）、`--out`、`--fit`、`--position`、`--oe`，可选 `--scene` 背景照。
- 适配数据来源：`data/normalized/sku_master.csv` 的 `oe_number / vehicle_make / vehicle_model / year_from / year_to / position`。**脚本本身不读这张表**，操作者必须从表里把值抄进命令行参数，不许凭记忆手打（手打是错图的主要来源）；字段口径见 `system/DATA-CONTRACT.md`。
- 若传 `--scene` 场景照，必须是**操作者已人工确认无任何车标**的照片；脚本不会识别背景车里的车标。

## 运行与输出

在仓库根目录执行：

```bash
# 在仓库根目录执行；用 install_skills.py 软链安装的，把 skills/ 换成 ~/.agents/skills/ 下的实际路径
# 1) 像素合规检查（主图最严）
python3 skills/amz-listing-images/scripts/img_check.py path/main.jpg --role main
python3 skills/amz-listing-images/scripts/img_check.py path/02.jpg path/03.jpg --role secondary

# 2) 生成适配车型卡（副图/A+ 用，输出 DRAFT，不能当首图）
python3 skills/amz-listing-images/scripts/make_fitment_card.py \
  --product path/product_nobg.png \
  --out path/fitment-01.jpg \
  --fit "2015-2018 Honda Accord" \
  --position "Front Left Lower" \
  --oe "51360-TVA-A00" \
  [--scene path/scene.jpg]

# 3) 去背景（可选，外部工具）
rembg i raw/part.jpg work/part_nobg.png
```

输出约定：

- `img_check.py`：逐图打印错误 / 警告 / 需复核；**有错误即非零退出**。无论是否报错，都会固定附两条需复核说明——“文字/水印无法自动判定”和“HOLD：没有车标识别能力，技术通过不构成可发布结论”。主图判据：背景区域白像素占比 ≥97%、产品沿长边方向占画幅 ≥85%、短边 ≥2000px、主图不含透明通道。
- `make_fitment_card.py`：生成 2000×2000 JPG，打印 **DRAFT（草稿，非可发布结论）** 与 HOLD 提醒；若 `--fit/--position/--oe` 拼接文字命中车标触发词，直接非零退出 HOLD，改完再出图。

## 示例

```bash
# 先确认依赖；对真实图片跑检查（<SKU> 是占位，替换成本地路径）
python3 -c "import PIL, numpy"
python3 skills/amz-listing-images/scripts/img_check.py assets/raw/<SKU>/main.jpg --role main
python3 skills/amz-listing-images/scripts/make_fitment_card.py \
  --product assets/raw/<SKU>/part_nobg.png \
  --out assets/listing/<SKU>/fitment-01.jpg \
  --fit "<年款> <品牌> <车型>" \
  --position "<安装位置>" \
  --oe "<OE 号>"
```

- 上例命令可直接照抄，方括号占位换成 `sku_master.csv` 里的真实值即可；这里不写死任何销量、金额或“已通过”的判定结果。
- 典型输出是“◐ 技术通过(发布仍HOLD)”或“✗ 不合规”。技术通过后仍要人工复核车标与文字；**不要**把一次命令成功解读成“图可以发了”。

## 失败降级

- 缺 Pillow/numpy：先装依赖再跑，不要因为脚本报错就默认图合规。
- 图片路径不存在：脚本打印“找不到文件”并计入失败，不跳过。
- 适配卡文字命中车标触发词：非零退出 HOLD，须改文案后重跑（见 `skills/_shared/metrics.py` 的 `brand_logo_hold`）。
- 传了 `--scene` 但照片可能带车标：脚本识别不了，标 `needs_human_review`；不传 `--scene` 时脚本用渐变背景，从构造上就不含车。
- 中文字体缺失变豆腐块：换机器后第一张适配卡必须肉眼确认字体回退正常。
- 任何情况下像素检查全绿：仍停在 **HOLD**，等人工车标/文字复核完成。

## 数据质量限制

- 脚本只判：背景白度、长边产品跨度、短边尺寸、透明通道、四周边色边带。**判不了**图里的促销文字、价格、水印、竞品 logo、整车厂车标、轮毂中心徽标、方向盘标、背景车。
- 主图占比用“长边跨度 ≥85%”而非面积占比——细长零件（控制臂等）面积永远到不了 85%，用面积判会全部误杀；这条对全部汽配细长件成立。
- 白底判据看“背景区域内的白像素 ≥97%”，不是全图白像素比例（产品占 85% 时全图白像素本就只有约 15%）。
- 无任何视觉/OCR/图像识别能力；`rembg`、IC-Light、ComfyUI 是可选外部工具，许可证各管各的，仓库不内置、不保证其输出无车标。

## 人工确认边界

- 上传、发布、改价、上广告一律由人批准；本技能不执行任何外部写操作。
- **车标是用户定义的发布硬阻断（A9，适用于全部汽配）**：主图/副图/适配卡/背景车里一旦出现整车厂品牌图形标识本身（奔驰三叉星、BMW 蓝白圆标、丰田三椭圆、福特蓝椭圆等），一律 `NO-GO`，必须移除或替换后重新复核。
- **不扩大化**：“fits Toyota Camry 2018”、OE 号、“replaces OEM …”这类 YMM/OE 适配**文字不是车标**，不因本规则自动阻断，仍走既有商标/证据审核。
- **无图像识别能力时的硬规则**：所有图片即使像素检查全过，在人工逐张车标复核完成前保持发布 HOLD；技术通过 ≠ 可发布。下游合规门禁见 `skills/amz-compliance-tax-logistics/`。
- 场景图只能放副图或 A+，不能当首图；不拿竞品图改。

## 追溯与验证

- 像素检查脚本：`skills/amz-listing-images/scripts/img_check.py`
- 适配卡脚本：`skills/amz-listing-images/scripts/make_fitment_card.py`
- 车标触发词逻辑：`skills/_shared/metrics.py`（`brand_logo_hold`）
- 适配字段口径：`system/DATA-CONTRACT.md`（`sku_master`）
- 亚马逊图片官方规范：https://sellercentral.amazon.com/help/hub/reference/external/G1881
- 关联技能：`skills/amz-listing-audit/`、`skills/amz-compliance-tax-logistics/`（车标门禁交接）
- 验证：主图必须 0 错误、副图无错误（警告逐条人工确认）；换机器后第一张中文图肉眼核字体；人工车标复核要留痕（哪张图、谁核、结论）。

## 高级规则

### 亚马逊硬规则速查

| 项 | 要求 | 谁检查 |
| --- | --- | --- |
| 主图背景 | 背景区域白像素占比 ≥97%（在背景区域内判纯白，非全图比例） | 脚本 |
| 主图产品占比 | 产品沿长边方向占画幅 ≥85%（细长件用跨度，非面积） | 脚本 |
| 尺寸 | 短边 ≥2000px（放大镜 1000 起，2000+ 体验最好） | 脚本 |
| 透明通道 | 主图不允许（会出灰边） | 脚本 |
| 四周边色边带 | 纯色边带 → 警告 | 脚本 |
| 边框/水印/促销文字/价格 | 禁止 | 人工 |
| 文字、logo、整车厂车标、他人品牌 | 禁止（副图/A+ 也只允许说明性文字） | 人工 |
| 场景图 | 只能放副图或 A+，不能当首图 | 人工 |

### 出图流程

1. **先定图位**：主图 1 张（白底单品）、副图 3–6 张（细节/材质/适配/安装位置/对比）。
2. **主图**：原图去背 → 合成纯白底 → 放大到长边占 85% → 存 JPG → `img_check --role main` 必须 0 错误。
3. **适配图**：从 `sku_master` 抄 `year_from/year_to/vehicle_make/vehicle_model/position/oe_number` 进命令行，**不许手打**。
4. **场景**：背景用人工确认无车标的道路照片或脚本渐变；产品贴上去；左下信息卡写年款车型 + 位置 + OE 号。
5. **合规**：不写价格、不写 best/No.1、不写竞品名、不贴车标（含背景车）。
6. **验收**：每张图跑 `img_check`；主图 0 错误，副图警告逐条看；再人工逐张复核车标/文字。
7. **归档**：成品进 `assets/listing/<sku>/`，原图进 `assets/raw/<sku>/`，可在 `assets/MANIFEST.md` 记一行（sku、图位、生成脚本版本、校验与人工复核结论）。

### 常见坑

- **场景图当首图 = 违规**。亚马逊主图必须纯白底，这条最常被忽略。
- **背景车带车标 = 侵权风险**。生成或选图后放大车头/车尾/轮毂中心/方向盘检查一遍。
- **中文会变豆腐块**：macOS 各版本字体路径不同，脚本已按 PingFang/Hiragino/STHeiti/Arial Unicode 回退；换机器后第一张图务必肉眼确认。
- **透明通道**：PNG 直接上传，亚马逊转白底时边缘发灰，先自己合成白底。
- **产品占比不足**：原图四周留白太多，裁完再放大，别用拉伸。
- **不要拿竞品图改**：既不合法也容易被投诉。

### 外部参考（可选工具）

- 去背景 rembg：https://github.com/danielgatis/rembg（MIT）
- 重打光 IC-Light（可选）：https://github.com/lllyasviel/IC-Light（Apache-2.0）
- 本地生成式场景 ComfyUI（可选）：https://github.com/comfyanonymous/ComfyUI（GPL-3.0，许可证只约束软件本身）
