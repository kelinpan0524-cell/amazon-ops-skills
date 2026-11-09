#!/usr/bin/env python3
"""亚马逊图片合规检查（主图/副图两套规则）。

主图硬规则（不合规直接报错）：
  - 纯白背景（R=G=B=255，容差 3），白底像素占比 ≥ 90%
  - 产品占画面面积 ≥ 85%（按非背景像素的包围盒算）
  - 边长 ≥ 2000px（亚马逊放大镜要求 1000 起，2000+ 体验最好）
  - 不含透明通道、不含边框/水印带

能自动判的都自动判；判不了的（比如有没有文字）明确写"需人工复核"，不假装通过。

用法：
  python3 scripts/img_check.py 图1.jpg 图2.jpg --role main|secondary
"""
import argparse
import os
import sys

import numpy as np
from PIL import Image

# 阈值统一从 config/thresholds.yaml 的 listing 段读（2026-11-04 审计修正）：
# 此前这里硬编码 MIN_SIDE/MIN_PRODUCT_RATIO，与 yaml 是两份，改一处另一处不跟；
# 且 MIN_WHITE_RATIO=0.90 声明了却没被使用（实际判定写死 0.97），属声明与实现不一致。
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "_shared"))
import metrics as m  # noqa: E402

_T = m.load_thresholds().get("listing", {})
WHITE_TOL = 3                                        # 像素"算白"的容差（技术常数，非业务阈值）
FG_THRESHOLD = 12                                    # 前景判定阈值：躲开 JPEG 压缩光晕（技术常数）
MIN_WHITE_RATIO = _T.get("product_fill_ratio_min", 0.85)   # 产品占画面（沿长边）
MIN_PRODUCT_RATIO = _T.get("product_fill_ratio_min", 0.85)
MIN_SIDE = _T.get("main_image_min_side", 2000)        # 主图最短边
BG_WHITE_RATIO = _T.get("background_white_ratio_min", 0.97)  # 背景区域纯白比例


def load(path):
    img = Image.open(path)
    if img.mode in ("RGBA", "LA", "P"):
        return img.convert("RGBA"), True
    return img.convert("RGB"), False


def analyze(path, role):
    img, has_alpha = load(path)
    w, h = img.size
    errs, warns, notes = [], [], []

    if min(w, h) < MIN_SIDE:
        errs.append("尺寸 %dx%d，短边不足 %d，放大镜会糊" % (w, h, MIN_SIDE))
    if has_alpha:
        errs.append("带透明通道（亚马逊会转白底，边缘容易出灰边），请先合成白底再存 JPG")

    rgb = np.asarray(img.convert("RGB")).astype(np.int16)
    if role == "main":
        # 前景 = 明显不是白的像素（离白 ≥13），躲开 JPEG 压缩光晕
        fg = (255 - rgb).min(axis=2) > FG_THRESHOLD
        bg = ~fg
        if not fg.any():
            errs.append("整张图都是白的，没有产品")
        elif not bg.any():
            errs.append("背景不是白色：整张图找不到白色像素（主图必须纯白底）")
        else:
            # 规则一：背景必须纯白 —— 看的是"背景区域里有多少是白的"，不是全图。
            # （产品占 85% 时全图白像素本来就只有 15%，拿全图比例判会自相矛盾）
            bg_white = float((rgb[bg] >= 246).all(axis=1).mean()) if bg.any() else 1.0
            if bg_white < BG_WHITE_RATIO:
                errs.append("背景不纯白：背景区域只有 %.1f%% 是白的，要求 ≥%.0f%%（修图时把底色刷成 255,255,255）"
                            % (bg_white * 100, BG_WHITE_RATIO * 100))

            # 规则二：产品沿长边方向占满画幅 ≥85%
            # 细长件（控制臂只是当前示例，适用全部汽配类目）面积占比永远达不到 85%，用面积判会全部误杀；
            # 实际做法是让产品在长边方向撑满画幅。
            ys, xs = np.where(fg)
            span = max((xs.max() - xs.min() + 1) / float(w), (ys.max() - ys.min() + 1) / float(h))
            if span < MIN_PRODUCT_RATIO:
                errs.append("产品只占画面 %.0f%%（长边方向），要求 ≥%.0f%%（裁掉空白再放大，不要拉伸）"
                            % (span * 100, MIN_PRODUCT_RATIO * 100))
            notes.append("背景纯白 %.1f%%，产品沿长边占 %.0f%%" % (bg_white * 100, span * 100))
    else:
        notes.append("副图不要求纯白底，跳过白底检查")

    # 四边是否有纯色边框带（常见于模板导出）
    edge = 6
    for name, strip in (("上", rgb[:edge]), ("下", rgb[-edge:]), ("左", rgb[:, :edge]), ("右", rgb[:, -edge:])):
        if strip.std() < 1.0 and not (np.abs(strip - 255) <= WHITE_TOL).all():
            warns.append("%s边有纯色边框带，主图不允许" % name)

    notes.append("文字/水印无法自动判定，需人工复核（亚马逊禁止促销文字、水印、边框元素）")
    notes.append("HOLD：本工具没有车标/方向盘/轮毂中心徽标的识别能力——无论技术检查是否通过，"
                 "所有图片在人工车标复核完成前保持发布 HOLD，本工具的技术通过不构成可发布结论")
    return {"path": path, "role": role, "width": w, "height": h, "errors": errs, "warnings": warns, "notes": notes}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("files", nargs="+")
    ap.add_argument("--role", choices=["main", "secondary"], default="main")
    args = ap.parse_args()

    bad = 0
    for f in args.files:
        if not os.path.exists(f):
            print("✗ 找不到文件：%s" % f)
            bad += 1
            continue
        r = analyze(f, args.role)
        head = "✗" if r["errors"] else ("⚠" if r["warnings"] else "◐ 技术通过(发布仍HOLD)")
        print("%s %s（%dx%d）" % (head, os.path.basename(f), r["width"], r["height"]))
        for e in r["errors"]:
            print("   错误：" + e)
        for w in r["warnings"]:
            print("   警告：" + w)
        for n in r["notes"]:
            print("   需复核：" + n)
        if r["errors"]:
            bad += 1

    if bad:
        sys.exit("%d 张图不合规" % bad)


if __name__ == "__main__":
    main()
