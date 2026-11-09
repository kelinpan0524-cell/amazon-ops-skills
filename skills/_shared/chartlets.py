#!/usr/bin/env python3
"""SVG 图表库：所有技能共用的画图层（纯标准库、零 JS、单文件可离线打开）。

设计约束（2026-11-04 可视化调研结论）：
  - 图表是「画好的 SVG」，不依赖任何 JavaScript——飞书云盘 HTML 预览沙箱大概率
    不执行 JS，ECharts 类方案在预览里是空白；SVG 任何环境打开都有图；
  - 中文用系统字体栈（PingFang SC / 微软雅黑），不内嵌字体文件；
  - 每个函数吃 Python 原生数据结构、吐 SVG/HTML 字符串；不写文件（调用方落盘）；
  - 缺值（None）跳过该点并断线，绝不画成 0。

颜色语义：绿=好、红=坏（与仓库 degraded 红警一致）；金额展示一律由调用方带单位。
"""
from __future__ import annotations

BLUE = "#2563eb"
GREEN = "#16a34a"
RED = "#dc2626"
AMBER = "#d97706"
GRAY = "#6b7280"
LIGHT = "#f3f4f6"
GRID = "#e5e7eb"
PALETTE = [BLUE, "#0d9488", "#7c3aed", AMBER, "#db2777", "#0891b2", "#65a30d", "#9333ea"]


def esc(s) -> str:
    """XML 转义（标题/标签里可能有 & < > 和引号）。"""
    return (str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            .replace('"', "&quot;"))


def _fmt(v, nd=0):
    """数字格式化：千分位，None 返回 '-'。默认 0 位小数（报告不带小数点）。"""
    if v is None:
        return "-"
    try:
        return ("{:,.%df}" % nd).format(v)
    except (TypeError, ValueError):
        return str(v)


def money_usd(v) -> str:
    """金额统一整数显示：$59,648（不带小数、不带 ÷ 后的零头）。None → '-'. """
    if v is None:
        return "-"
    return "$%s" % _fmt(round(float(v)))


def pct_int(v, nd=1) -> str:
    """百分比：默认 1 位小数（ACOS 9.2%）；整数百分比用 pct_int(x, 0)。None → '缺数据'。"""
    if v is None:
        return "缺数据"
    return "%s%%" % _fmt(v * 100, nd)


def _nice_max(values) -> float:
    """轴上限取整（1/2/5×10^n），避免顶到边框。"""
    mx = max([abs(v) for v in values if v is not None] or [1]) or 1
    mag = 1
    while mx > mag * 10:
        mag *= 10
    for step in (1, 2, 5, 10):
        if mx <= mag * step:
            return mag * step
    return mag * 10


def kpi_cards(cards) -> str:
    """KPI 卡片行。cards: [{"label","value","delta","delta_good","note"}]。
    delta 是环比（小数，如 0.12=+12%）；delta_good=True 时涨为绿（默认），
    对「成本/ACOS」类指标传 delta_good=False（涨=红）。"""
    out = ['<div class="kpi-row">']
    for c in cards:
        delta_html = ""
        d = c.get("delta")
        if d is not None:
            up = d >= 0
            good = (up == c.get("delta_good", True))
            color = GREEN if good else RED
            arrow = "▲" if up else "▼"
            delta_html = '<div class="kpi-delta" style="color:%s">%s %.1f%%</div>' % (
                color, arrow, d * 100)
        note = '<div class="kpi-note">%s</div>' % esc(c["note"]) if c.get("note") else ""
        out.append(
            '<div class="kpi-card"><div class="kpi-label">%s</div>'
            '<div class="kpi-value">%s</div>%s%s</div>'
            % (esc(c["label"]), esc(c["value"]), delta_html, note))
    out.append("</div>")
    return "".join(out)


def line_chart(labels, series, w=720, h=260, y_fmt="int", title="", y2_series=None,
               y2_fmt="pct") -> str:
    """折线图（可多系列；y2_series 画副轴，如 ACOS% 叠在花费柱上）。
    labels: x 轴标签列表；series: [{"name","values"(可含 None),"color"}]
    y_fmt: int/money/pct；副轴同理。None 值断开不画。"""
    pad_l, pad_r, pad_t, pad_b = 64, 16, 26, 34
    iw, ih = w - pad_l - pad_r, h - pad_t - pad_b
    n = max(len(labels), 1)
    all_v = [v for s in series for v in s["values"] if v is not None]
    ymax = _nice_max(all_v) if all_v else 1
    has_y2 = bool(y2_series)
    pad_r = 56 if has_y2 else pad_r
    iw = w - pad_l - pad_r

    def x(i):
        return pad_l + iw * i / max(n - 1, 1)

    def y(v, mx=ymax):
        return pad_t + ih * (1 - (v or 0) / mx)

    # max-width：.chart 是 width:100%，放进 flex 行里会被拉到整行宽，
    # 300×250 的环被拉成 700 宽就扁了（2026-11-04 总览报告里看到）。
    parts = ['<svg viewBox="0 0 %d %d" class="chart" role="img" style="max-width:%dpx">' % (w, h, w)]
    if title:
        parts.append('<text x="%d" y="15" class="chart-title">%s</text>' % (pad_l, esc(title)))
    # 网格 + y 轴刻度（4 条）
    for g in range(5):
        gy = pad_t + ih * g / 4
        parts.append('<line x1="%d" y1="%.1f" x2="%d" y2="%.1f" stroke="%s" stroke-width="1"/>'
                     % (pad_l, gy, w - pad_r, gy, GRID))
        val = ymax * (1 - g / 4)
        txt = ("{:.0f}%".format(val * 100)) if y_fmt == "pct" else _fmt(val)
        parts.append('<text x="%d" y="%.1f" class="tick" text-anchor="end">%s</text>'
                     % (pad_l - 6, gy + 4, txt))
    # x 轴标签（最多 8 个，多了抽样）
    step = max(1, (n + 7) // 8)
    for i, lab in enumerate(labels):
        if i % step or i != n - 1 and (i % step != 0):
            continue
        parts.append('<text x="%.1f" y="%d" class="tick" text-anchor="middle">%s</text>'
                     % (x(i), h - 10, esc(lab)))
    # 副轴刻度：贴右边缘右对齐（放 start 会向左侵入绘图区，与数据点标签打架）
    if has_y2:
        all_v2 = [v for s in y2_series for v in s["values"] if v is not None]
        ymax2 = _nice_max(all_v2) if all_v2 else 1
        for g in range(5):
            val = ymax2 * (1 - g / 4)
            txt = ("{:.0f}%".format(val * 100)) if y2_fmt == "pct" else _fmt(val)
            gy = pad_t + ih * g / 4
            parts.append('<text x="%d" y="%.1f" class="tick" text-anchor="end">%s</text>'
                         % (w - 2, gy + 4, txt))
    # 系列
    def draw(s, mx, dash=""):
        color = s.get("color") or BLUE
        d, dots = [], []
        for i, v in enumerate(s["values"]):
            if v is None:
                continue
            d.append("%s%.1f,%.1f" % ("M" if (not d or s["values"][max(0, i - 1)] is None) else "L",
                                      x(i), y(v, mx)))
            dots.append((i, v, mx))
        if d:
            parts.append('<path d="%s" fill="none" stroke="%s" stroke-width="2"%s/>'
                         % (" ".join(d), color, ' stroke-dasharray="5 4"' if dash else ""))
        for i, v, mx2 in dots:
            parts.append('<circle cx="%.1f" cy="%.1f" r="3" fill="%s"/>'
                         % (x(i), y(v, mx2), color))
        # 每点数值（点少时全标，多时只标末点）
        # 边界约束：文字宽度按字符估算（数字 6px/字符），靠右的标签右对齐并夹在画布内，
        # 防止 "297,867.5" 这类长数字冲出 viewBox（2026-11-04 实测溢出 7px）。
        def _label(ix, vv, mmx, anchor_hint="middle"):
            txt = _fmt(vv, 1 if y_fmt == "money" else 0)
            est_w = len(txt) * 6.0
            cx = x(ix)
            py = y(vv, mmx)
            # 垂直避让：太靠顶（会压到标题/图例）就放到点下方；太靠底就放到上方
            ly = py + 14 if py - 7 < pad_t + 10 else py - 7
            # 水平避让：贴左右边缘时改对齐方式，保证不出画布
            if cx + est_w / 2 > w - 4:
                return ('<text x="%.1f" y="%.1f" class="pt" text-anchor="end">%s</text>'
                        % (w - 4, ly, txt))
            if cx - est_w / 2 < pad_l:
                return ('<text x="%.1f" y="%.1f" class="pt" text-anchor="start">%s</text>'
                        % (pad_l, ly, txt))
            return ('<text x="%.1f" y="%.1f" class="pt" text-anchor="middle">%s</text>'
                    % (cx, ly, txt))

        if len(dots) <= 10:
            for i, v, mx2 in dots:
                parts.append(_label(i, v, mx2))
        else:
            i, v, mx2 = dots[-1]
            parts.append(_label(i, v, mx2, "end"))

    for si, s in enumerate(series):
        draw(s, ymax)
    if has_y2:
        for s in y2_series:
            draw(s, ymax2)
    # 图例（右对齐，避开左上标题）
    all_series = list(series) + list(y2_series or [])
    legend_w = sum(24 + 13 * max(len(s["name"]) * 0.95, 3) for s in all_series)
    legend_x = w - pad_r - legend_w
    for s in all_series:
        color = s.get("color") or BLUE
        parts.append('<rect x="%d" y="3" width="10" height="10" rx="2" fill="%s"/>'
                     % (legend_x, color))
        parts.append('<text x="%d" y="12" class="legend">%s</text>' % (legend_x + 14, esc(s["name"])))
        legend_x += 24 + 13 * max(len(s["name"]) * 0.95, 3)
    parts.append("</svg>")
    return "".join(parts)


def bar_chart(labels, values, w=720, h=240, color=BLUE, title="", y_fmt="int") -> str:
    """柱状图（单系列）。values 可含 None（空档不画）。"""
    pad_l, pad_r, pad_t, pad_b = 64, 16, 26, 30
    iw, ih = w - pad_l - pad_r, h - pad_t - pad_b
    n = max(len(labels), 1)
    ymax = _nice_max([v for v in values if v is not None] or [1])
    bw = max(4.0, iw / n * 0.62)
    parts = ['<svg viewBox="0 0 %d %d" class="chart" role="img">' % (w, h)]
    if title:
        parts.append('<text x="%d" y="15" class="chart-title">%s</text>' % (pad_l, esc(title)))
    for g in range(5):
        gy = pad_t + ih * g / 4
        parts.append('<line x1="%d" y1="%.1f" x2="%d" y2="%.1f" stroke="%s"/>'
                     % (pad_l, gy, w - pad_r, gy, GRID))
        val = ymax * (1 - g / 4)
        txt = ("{:.0f}%".format(val * 100)) if y_fmt == "pct" else _fmt(val)
        parts.append('<text x="%d" y="%.1f" class="tick" text-anchor="end">%s</text>'
                     % (pad_l - 6, gy + 4, txt))
    for i, (lab, v) in enumerate(zip(labels, values)):
        cx = pad_l + iw * (i + 0.5) / n
        if v is not None:
            bh = ih * v / ymax
            parts.append('<rect x="%.1f" y="%.1f" width="%.1f" height="%.1f" rx="3" fill="%s"/>'
                         % (cx - bw / 2, pad_t + ih - bh, bw, bh, color))
            parts.append('<text x="%.1f" y="%.1f" class="pt" text-anchor="middle">%s</text>'
                         % (cx, pad_t + ih - bh - 5, _fmt(v)))
        step = max(1, (n + 9) // 10)
        if i % step == 0 or i == n - 1:
            parts.append('<text x="%.1f" y="%d" class="tick" text-anchor="middle">%s</text>'
                         % (cx, h - 8, esc(lab)))
    parts.append("</svg>")
    return "".join(parts)


def hbar_chart(rows, w=720, title="", unit="", max_val=None) -> str:
    """水平条排行。rows: [{"label","value","color"(可选),"note"}]

    布局：左标签 | 条形区 | 右数值+note（右对齐）。右栏按 note 长度动态留宽，
    防止「$152,906 环比-0%」被截断成「1」。
    """
    row_h = 34
    pad_label = 132
    # 右侧栏宽：数值（最多 9 字符）+ note（按中文 13px 估宽）
    max_note_len = max((len(str(r.get("note") or "")) for r in rows), default=0)
    pad_right = int(96 + max_note_len * 11)
    pad_right = min(pad_right, int(w * 0.45))
    bar_w = max(w - pad_label - pad_right, 60)
    h = 30 + row_h * max(len(rows), 1) + 6
    vals = [r["value"] for r in rows if r.get("value") is not None]
    mx = _nice_max([abs(v) for v in vals] or [1]) if max_val is None else max_val
    parts = ['<svg viewBox="0 0 %d %d" class="chart" role="img">' % (w, h)]
    if title:
        parts.append('<text x="8" y="16" class="chart-title">%s</text>' % esc(title))
    for i, r in enumerate(rows):
        y0 = 26 + i * row_h
        v = r.get("value")
        color = r.get("color") or BLUE
        parts.append('<text x="%d" y="%.1f" class="hlabel" text-anchor="end">%s</text>'
                     % (pad_label - 8, y0 + 14, esc(r["label"])))
        parts.append('<rect x="%d" y="%.1f" width="%d" height="20" rx="4" fill="%s"/>'
                     % (pad_label, y0, bar_w, LIGHT))
        if v is not None:
            bw = max(2.0, bar_w * min(abs(v) / mx, 1))
            parts.append('<rect x="%d" y="%.1f" width="%.1f" height="20" rx="4" fill="%s"/>'
                         % (pad_label, y0, bw, color))
        note = (" %s" % r["note"]) if r.get("note") else ""
        parts.append('<text x="%d" y="%.1f" class="hval" text-anchor="end">%s%s</text>'
                     % (w - 4, y0 + 14, _fmt(v) + unit, esc(note)))
    parts.append("</svg>")
    return "".join(parts)


def donut(parts_list, w=280, h=230, title="") -> str:
    """环形占比图。parts_list: [{"label","value","color"(可选)}]，自动算占比。"""
    total = sum(p.get("value") or 0 for p in parts_list)
    cx, cy, r, rw = w / 2, (h - 26) / 2 + 10, min(w, h - 30) / 2 - 18, 26
    # max-width：.chart 是 width:100%，进 flex 行会被拉到整行宽，
    # 300×250 的环拉成 700 宽就扁了（2026-11-04 总览报告里看到）。
    parts = ['<svg viewBox="0 0 %d %d" class="chart" role="img" style="max-width:%dpx">' % (w, h, w)]
    if title:
        parts.append('<text x="%d" y="16" class="chart-title" text-anchor="middle">%s</text>'
                     % (w / 2, esc(title)))
    import math
    if total > 0:
        ang = -90.0
        for i, p in enumerate(parts_list):
            v = p.get("value") or 0
            if v <= 0:
                continue
            frac = v / total
            a2 = ang + frac * 360
            large = 1 if frac > 0.5 else 0
            x1, y1 = cx + r * math.cos(math.radians(ang)), cy + r * math.sin(math.radians(ang))
            x2, y2 = cx + r * math.cos(math.radians(a2)), cy + r * math.sin(math.radians(a2))
            parts.append(
                '<path d="M %.1f %.1f A %.1f %.1f 0 %d 1 %.1f %.1f" fill="none" '
                'stroke="%s" stroke-width="%d"/>' % (x1, y1, r, r, large, x2, y2,
                                                     p.get("color") or PALETTE[i % len(PALETTE)], rw))
            ang = a2
    else:
        parts.append('<circle cx="%.1f" cy="%.1f" r="%.1f" fill="none" stroke="%s" stroke-width="%d"/>'
                     % (cx, cy, r, GRID, rw))
    parts.append('<text x="%.1f" y="%.1f" class="donut-center" text-anchor="middle">%s</text>'
                 % (cx, cy + 4, "合计" if total > 0 else "无数据"))
    # 图例（底部一行，放不下时截断到能放下为止）
    ly = h - 8
    lx = 8
    for i, p in enumerate(parts_list):
        color = p.get("color") or PALETTE[i % len(PALETTE)]
        pct = (p.get("value") or 0) / total * 100 if total else 0
        item_w = 26 + 13 * max(len(str(p["label"])) * 0.95, 3)
        if lx + item_w > w - 4:
            break
        parts.append('<rect x="%d" y="%d" width="9" height="9" rx="2" fill="%s"/>' % (lx, ly - 9, color))
        parts.append('<text x="%d" y="%d" class="legend">%s %.0f%%</text>'
                     % (lx + 13, ly, esc(p["label"]), pct))
        lx += item_w
    parts.append("</svg>")
    return "".join(parts)


def progress_bar(actual, target, time_pct=None, w=720, h=96,
                 title="", unit="$", label="") -> str:
    """目标达成进度条：一条主进度（实际/目标）+ 一条时间进度刻度线。

    time_pct 是"时间过到哪了"（如 10 月/12 月 = 83.3%）——只画一根竖刻度线，
    不画第二条进度条，避免读者分不清"哪个是哪个"。
    """
    pct = (actual / target) if (target and target > 0) else 0.0
    bar_w = w - 32
    bar_y, bar_h = 46, 26
    parts = ['<svg viewBox="0 0 %d %d" class="chart" role="img">' % (w, h)]
    if title:
        parts.append('<text x="8" y="18" class="chart-title">%s</text>' % esc(title))

    # 底槽
    parts.append('<rect x="16" y="%d" width="%d" height="%d" rx="6" fill="%s"/>'
                 % (bar_y, bar_w, bar_h, LIGHT))
    # 实际进度（超 100% 用绿色，未达标用蓝色）
    filled = max(0.0, min(pct, 1.0)) * bar_w
    color = GREEN if pct >= 1 else BLUE
    if filled > 0:
        parts.append('<rect x="16" y="%d" width="%.1f" height="%d" rx="6" fill="%s"/>'
                     % (bar_y, filled, bar_h, color))
    # 时间进度刻度
    if time_pct is not None:
        tx = 16 + max(0.0, min(time_pct, 1.0)) * bar_w
        parts.append('<line x1="%.1f" y1="%d" x2="%.1f" y2="%d" stroke="%s" '
                     'stroke-width="2" stroke-dasharray="4 3"/>'
                     % (tx, bar_y - 6, tx, bar_y + bar_h + 6, GRAY))
        parts.append('<text x="%.1f" y="%d" class="tick" text-anchor="middle">'
                     '时间进度 %.0f%%</text>' % (tx, bar_y + bar_h + 20, time_pct * 100))
    # 左右数值
    parts.append('<text x="16" y="%d" class="hval">%s%s</text>'
                 % (bar_y - 8, unit, _fmt(round(actual))))
    parts.append('<text x="%d" y="%d" class="tick" text-anchor="end">目标 %s%s</text>'
                 % (w - 16, bar_y - 8, unit, _fmt(round(target))))
    # 中心百分比
    parts.append('<text x="%.1f" y="%d" class="donut-center" text-anchor="middle" '
                 'style="fill:#fff;font-weight:700">%.1f%%</text>'
                 % (16 + bar_w / 2, bar_y + bar_h - 8, pct * 100))
    if label:
        parts.append('<text x="16" y="%d" class="tick">%s</text>' % (h - 6, esc(label)))
    parts.append("</svg>")
    return "".join(parts)
