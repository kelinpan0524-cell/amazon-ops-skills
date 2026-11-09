#!/usr/bin/env python3
"""生成汽配「适配车型」场景图（副图/A+ 用，不能当首图）。

构图：场景背景（渐变或传入照片）+ 产品（去背 PNG，居中偏右）+ 左下角信息卡
      （适用年款/车型/位置/OE 号）+ 右下角 OE 对照提示。

红线：
- 背景车不出现任何车标（本脚本不生成车，只叠你提供的无标识背景图或用渐变）
- 不写价格、不写促销、不写"best/No.1"
- 车型年款必须来自 sku_master，不许手写（防出错图）

用法：
  python3 scripts/make_fitment_card.py --product 产品.png --out 出图.jpg \
      --fit "2015-2018 Honda Accord" --position "Front Left" --oe "51360-TVA-A00" \
      --scene 场景.jpg
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "_shared"))
import metrics as m  # noqa: E402

from PIL import Image, ImageDraw, ImageFilter, ImageFont

W = H = 2000
CARD_BG = (255, 255, 255, 235)
INK = (24, 24, 27)
SUB = (90, 90, 99)
ACCENT = (16, 122, 87)


# 中文字体候选：macOS 不同版本路径不同，PingFang 在部分版本缺失（缺了中文会变成方块）
CJK_FONTS = [
    "/System/Library/Fonts/PingFang.ttc",
    "/System/Library/Fonts/Hiragino Sans GB.ttc",
    "/System/Library/Fonts/STHeiti Medium.ttc",
    "/System/Library/Fonts/Supplemental/Arial Unicode.ttf",
]


def font(size, bold=False):
    cands = list(CJK_FONTS) + [
        "/System/Library/Fonts/Supplemental/Arial Bold.ttf" if bold else "/System/Library/Fonts/Supplemental/Arial.ttf",
        "/System/Library/Fonts/Helvetica.ttc",
    ]
    for p in cands:
        if os.path.exists(p):
            try:
                return ImageFont.truetype(p, size)
            except Exception:
                continue
    return ImageFont.load_default()


def scene_background(path=None):
    """没有场景照片时用渐变，避免生成带车标的假车（误导 + 侵权风险）。"""
    if path:
        img = Image.open(path).convert("RGB").resize((W, H), Image.Resampling.LANCZOS)
        return img.filter(ImageFilter.GaussianBlur(2))
    base = Image.new("RGB", (W, H))
    d = ImageDraw.Draw(base)
    for y in range(H):
        t = y / H
        d.line([(0, y), (W, y)], fill=(int(232 - 40 * t), int(238 - 30 * t), int(244 - 20 * t)))
    # 地面阴影带，让产品看起来是"落地"的
    d.rectangle([0, int(H * 0.78), W, H], fill=(214, 219, 224))
    return base.filter(ImageFilter.GaussianBlur(1))


def paste_product(bg, product_path, box_ratio=0.42):
    p = Image.open(product_path).convert("RGBA")
    target = int(W * box_ratio)
    scale = target / max(p.size)
    p = p.resize((int(p.width * scale), int(p.height * scale)), Image.Resampling.LANCZOS)
    x = int(W * 0.52) - p.width // 2
    y = int(H * 0.52) - p.height // 2
    # 投影
    sh = Image.new("RGBA", p.size, (0, 0, 0, 0))
    sh.paste((0, 0, 0, 70), (0, 0), p.split()[-1])
    sh = sh.filter(ImageFilter.GaussianBlur(18))
    bg.paste(sh, (x + 12, y + 26), sh)
    bg.paste(p, (x, y), p)
    return bg


def info_card(img, fit, position, oe):
    d = ImageDraw.Draw(img, "RGBA")
    x0, y0, x1, y1 = 80, int(H * 0.70), int(W * 0.62), int(H * 0.93)
    d.rounded_rectangle([x0, y0, x1, y1], radius=28, fill=CARD_BG)
    d.rectangle([x0, y0, x0 + 12, y1], fill=ACCENT + (255,))

    d.text((x0 + 44, y0 + 34), "FITS", font=font(46, True), fill=ACCENT)
    d.text((x0 + 44, y0 + 100), fit, font=font(72, True), fill=INK)
    d.text((x0 + 44, y0 + 196), position, font=font(52), fill=INK)
    d.text((x0 + 44, y0 + 274), "OE: %s" % oe, font=font(44), fill=SUB)

    d.text((80, H - 92), "Refer to fitment data before ordering. Image for illustration.",
           font=font(34), fill=(60, 60, 66))
    d.text((80, H - 50), "适配以商品页年款车型为准", font=font(30), fill=(60, 60, 66))
    return img


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--product", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--fit", required=True)
    ap.add_argument("--position", default="")
    ap.add_argument("--oe", default="")
    ap.add_argument("--scene", default=None)
    args = ap.parse_args()

    # A9 车标硬阻断：文字输入命中即拒；传入场景照片可能含车标，图像侧无识别能力，必须人工复核
    hits = m.brand_logo_hold(" ".join([args.fit, args.position, args.oe]))
    if hits:
        sys.exit("HOLD：卡片文字命中车标触发词 %s——车标侵权硬阻断，改完再出图" % "、".join(hits))
    bg = scene_background(args.scene)
    bg = paste_product(bg, args.product)
    bg = info_card(bg, args.fit, args.position, args.oe)
    bg.convert("RGB").save(args.out, quality=92)
    print("DRAFT（草稿，非可发布结论）：%s（%dx%d）已生成，仅副图/A+ 用，不能当首图。" % (args.out, W, H))
    print("HOLD：本脚本没有任何车标识别能力——产品图、场景图与这张输出图都要人工逐张确认无")
    print("  车标/方向盘标/轮毂中心徽标；全部确认完成前不得进入发布流程（技术生成 ≠ 可发布）。")


if __name__ == "__main__":
    main()
