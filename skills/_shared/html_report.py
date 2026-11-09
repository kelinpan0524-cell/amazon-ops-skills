#!/usr/bin/env python3
"""HTML 报告骨架：标题区/结论条/正文区/口径脚注，单文件自包含（内嵌 CSS，零 JS）。

与 chartlets.py 配套：图表函数吐 SVG 字符串，本模块负责壳和排版。
写入用 pathlib（write_text）；打印友好（@media print 隐藏交互色块边框）。
"""
from __future__ import annotations

import re

from pathlib import Path

CSS = """
:root{--blue:#2563eb;--green:#16a34a;--red:#dc2626;--amber:#d97706;--ink:#111827;
--muted:#6b7280;--bg:#f8fafc;--card:#ffffff;--line:#e5e7eb}
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:-apple-system,BlinkMacSystemFont,'PingFang SC','Hiragino Sans GB',
'Microsoft YaHei',sans-serif;background:var(--bg);color:var(--ink);line-height:1.5;
padding:24px;max-width:980px;margin:0 auto}
.head{display:flex;justify-content:space-between;align-items:flex-end;
border-bottom:2px solid var(--ink);padding-bottom:10px;margin-bottom:14px}
h1{font-size:22px}
.sub{color:var(--muted);font-size:13px;margin-top:2px}
.meta{color:var(--muted);font-size:12px;text-align:right}
.banner{border-radius:10px;padding:12px 16px;margin-bottom:16px;font-size:15px;
border:1px solid var(--line);background:var(--card)}
.banner.good{border-left:5px solid var(--green)}
.banner.warn{border-left:5px solid var(--amber)}
.banner.bad{border-left:5px solid var(--red)}
.kpi-row{display:grid;grid-template-columns:repeat(auto-fit,minmax(140px,1fr));gap:10px;
margin-bottom:16px}
.kpi-card{background:var(--card);border:1px solid var(--line);border-radius:10px;
padding:12px 14px}
.kpi-label{font-size:12px;color:var(--muted)}
.kpi-value{font-size:22px;font-weight:700;margin:2px 0}
.kpi-delta{font-size:12px;font-weight:600}
.kpi-note{font-size:11px;color:var(--muted);margin-top:2px}
section{background:var(--card);border:1px solid var(--line);border-radius:10px;
padding:14px 16px;margin-bottom:14px}
section h2{font-size:15px;margin-bottom:8px}
.chart{width:100%;height:auto}
.chart-title{font-size:12px;font-weight:600;fill:var(--muted)}
.tick{font-size:10px;fill:var(--muted)}
.pt{font-size:10px;fill:#374151}
.legend{font-size:11px;fill:#374151}
.hlabel{font-size:11px;fill:#374151}
.hval{font-size:11px;fill:#111827;font-weight:600}
.donut-center{font-size:13px;fill:var(--muted)}
table{width:100%;border-collapse:collapse;font-size:13px;margin-top:6px}
th{background:var(--bg);text-align:left;font-weight:600;color:var(--muted);
font-size:12px;padding:6px 8px;border-bottom:1px solid var(--line)}
td{padding:6px 8px;border-bottom:1px solid #f1f5f9}
tr:last-child td{border-bottom:none}
.tag{display:inline-block;padding:1px 8px;border-radius:99px;font-size:11px;font-weight:600}
.tag.good{background:#dcfce7;color:#15803d}
.tag.warn{background:#fef3c7;color:#b45309}
.tag.bad{background:#fee2e2;color:#b91c1c}
ul.plain{list-style:none}
ul.plain li{padding:4px 0;border-bottom:1px dashed #f1f5f9;font-size:13px}
ul.plain li:last-child{border-bottom:none}
.foot{color:var(--muted);font-size:11px;border-top:1px solid var(--line);
padding-top:10px;margin-top:6px}
.prog{margin-top:4px}
.prog-head{display:flex;justify-content:space-between;font-size:13px;margin-bottom:6px}
.prog-head b{font-size:16px}
.prog-track{position:relative;height:26px;background:var(--bg);border-radius:8px;overflow:visible}
.prog-fill{height:26px;border-radius:8px;background:var(--blue);
display:flex;align-items:center;justify-content:flex-end;padding-right:8px;
color:#fff;font-size:12px;font-weight:700}
.prog-fill.over{background:var(--green)}
.prog-tick{position:absolute;top:-6px;bottom:-6px;width:0;border-left:2px dashed var(--muted)}
.prog-foot{margin-top:8px;font-size:12px;color:var(--muted);line-height:1.7}
.prog-legend{font-size:11px;color:var(--muted);margin-top:4px}
.prog-legend i{display:inline-block;width:14px;border-top:2px dashed var(--muted);
vertical-align:middle;margin:0 4px}
@media print{body{background:#fff;padding:8px}section,.kpi-card{break-inside:avoid}}
"""

HTML_SHELL = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{title}</title>
<style>{css}</style>
</head>
<body>
<div class="head">
  <div><h1>{title}</h1><div class="sub">{subtitle}</div></div>
  <div class="meta">{meta}</div>
</div>
{banner}
{body}
<div class="foot">{footer}</div>
</body>
</html>
"""


def banner(text, level="good"):
    """结论条。level: good / warn / bad。"""
    return '<div class="banner %s">%s</div>' % (level, text)


def section(title, inner_html):
    return '<section><h2>%s</h2>%s</section>' % (title, inner_html)


def progress(actual, target, time_pct=None, unit="$", fmt=None, foot="") -> str:
    """目标达成进度条（HTML 版）。

    为什么不用 SVG：宽高比 7:1 的 SVG 在页面里按宽度缩放后高度被压得很矮，字看不清；
    HTML+CSS 的高度是固定的、字号不随容器缩放，读起来稳。
    """
    fmt = fmt or (lambda v: "{:,.0f}".format(v))
    pct = (actual / target * 100) if (target and target > 0) else 0.0
    over = pct >= 100
    width = max(0.0, min(pct, 100.0))
    tick = ""
    if time_pct is not None:
        tick = ('<div class="prog-tick" style="left:%.1f%%"></div>'
                % max(0.0, min(time_pct * 100, 100.0)))
    return (
        '<div class="prog">'
        '<div class="prog-head"><span>已达成 <b>%s%s</b></span>'
        '<span>目标 %s%s</span></div>'
        '<div class="prog-track">'
        '<div class="prog-fill%s" style="width:%.1f%%">%.1f%%</div>%s</div>'
        '%s%s</div>'
        % (unit, fmt(actual), unit, fmt(target),
           " over" if over else "", width, pct, tick,
           ('<div class="prog-legend">虚线 <i></i> 时间进度（%.0f%%）</div>' % (time_pct * 100))
           if time_pct is not None else "",
           ('<div class="prog-foot">%s</div>' % foot) if foot else "")
    )


_ASIN_RE = re.compile(r"^B0[A-Z0-9]{8}$")


def linkify_asin(cell: str) -> str:
    """表格里看起来像 ASIN 的单元格自动变成亚马逊链接。

    运营看到 ASIN 的第一反应是"这是哪个产品"，让他点一下就能到前台页面，
    比复制去后台搜省事。只认**整格就是一个 ASIN** 的情况，
    避免把标题里的 "B0XXXXXXXX" 片段误包成链接。
    """
    s = str(cell).strip()
    if _ASIN_RE.match(s):
        return ('<a href="https://www.amazon.com/dp/%s" target="_blank" '
                'rel="noopener" style="color:#2563eb;text-decoration:none">%s</a>'
                % (s, s))
    return cell


def table(headers, rows, align_right=None):
    """明细表。rows 是二维列表；align_right 是要右对齐的列号集合。"""
    align_right = align_right or set()
    th = "".join("<th>%s</th>" % h for h in headers)
    trs = []
    for r in rows:
        tds = []
        for i, cell in enumerate(r):
            style = ' style="text-align:right"' if i in align_right else ""
            tds.append("<td%s>%s</td>" % (style, linkify_asin(cell)))
        trs.append("<tr>%s</tr>" % "".join(tds))
    return ('<div class="tbl-wrap"><div style="text-align:right;margin:2px 0 4px">'
            '<button type="button" data-export-xls style="font-size:12px;padding:3px 10px;'
            'border:1px solid #d1d5db;border-radius:6px;background:#f9fafb;cursor:pointer">'
            '⬇ 导出 Excel</button></div>'
            '<table data-sortable><thead><tr>%s</tr></thead><tbody>%s</tbody></table></div>'
            % (th, "".join(trs)))


# 表格交互（点表头排序 + 搜索框）。飞书云盘的 HTML 预览沙箱不执行脚本，
# 所以这段在飞书里不生效——但下载后用浏览器打开就能用。
# 不生效时表格照常显示，只是不能点，不会报错。
TABLE_JS = r"""
<script>
(function(){
  document.querySelectorAll('table[data-sortable]').forEach(function(tb){
    var body = tb.tBodies[0];
    tb.querySelectorAll('thead th').forEach(function(th, i){
      th.style.cursor = 'pointer';
      th.title = '点击排序';
      th.addEventListener('click', function(){
        var asc = th.dataset.asc !== '1';
        var rows = Array.prototype.slice.call(body.rows);
        rows.sort(function(a, b){
          var x = (a.cells[i] || {}).innerText || '', y = (b.cells[i] || {}).innerText || '';
          var nx = parseFloat(String(x).replace(/[^0-9.\-]/g, ''));
          var ny = parseFloat(String(y).replace(/[^0-9.\-]/g, ''));
          if (!isNaN(nx) && !isNaN(ny)) return asc ? nx - ny : ny - nx;
          return asc ? String(x).localeCompare(String(y)) : String(y).localeCompare(String(x));
        });
        rows.forEach(function(r){ body.appendChild(r); });
        th.dataset.asc = asc ? '1' : '0';
      });
    });
  });

  // 导出 Excel：优先 SheetJS 生成 .xlsx；CDN 不可用时回退 CSV（Excel 可直接打开）
  function csvFallback(tb){
    var lines = [];
    Array.prototype.forEach.call(tb.rows, function(r){
      var cells = [];
      Array.prototype.forEach.call(r.cells, function(td){
        var v = (td.innerText || '').replace(/"/g, '""');
        cells.push('"' + v + '"');
      });
      lines.push(cells.join(','));
    });
    var blob = new Blob(['\ufeff' + lines.join('\r\n')], {type: 'text/csv;charset=utf-8'});
    var a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = 'report-table.csv';
    a.click();
    URL.revokeObjectURL(a.href);
  }
  function exportTable(tb){
    function withSheetJS(cb, eb){
      if (window.XLSX) { cb(); return; }
      var s = document.createElement('script');
      s.src = 'https://cdn.jsdelivr.net/npm/xlsx@0.18.5/dist/xlsx.full.min.js';
      s.onload = cb; s.onerror = eb;
      document.head.appendChild(s);
    }
    withSheetJS(function(){
      var wb = XLSX.utils.table_to_book(tb, {sheet: '明细'});
      XLSX.writeFile(wb, 'report-table.xlsx');
    }, function(){ csvFallback(tb); });
  }
  document.querySelectorAll('button[data-export-xls]').forEach(function(btn){
    btn.addEventListener('click', function(){
      var wrap = btn.closest('.tbl-wrap');
      var tb = wrap ? wrap.querySelector('table') : null;
      if (tb) exportTable(tb);
    });
  });
  document.querySelectorAll('input[data-filter-table]').forEach(function(inp){
    inp.addEventListener('input', function(){
      var q = inp.value.trim().toLowerCase();
      var tb = document.getElementById(inp.dataset.filterTable);
      if (!tb) return;
      Array.prototype.forEach.call(tb.tBodies[0].rows, function(r){
        r.style.display = (!q || r.innerText.toLowerCase().indexOf(q) >= 0) ? '' : 'none';
      });
    });
  });
})();
</script>
"""


def methodology(rows, title="计算规则与预警标准"):
    """统一的「算法与阈值」说明区块。

    用户验收硬要求（2026-11-04）：每份报告都要写清指标怎么算、按什么口径、
    预警阈值是多少、为什么触发——不让运营对着一个数字猜来历。
    rows: [(指标/规则, 算法与阈值说明)]，第二列可含 <code> 等 HTML。
    """
    return section(title, table(["指标 / 规则", "算法、口径与阈值"], rows))


def table_filterable(table_html, table_id, placeholder="搜 SKU / ASIN / 产品名…"):
    """给表格加搜索框（浏览器里生效，飞书预览里只是个装饰）。"""
    return ('<div style="margin:0 0 8px"><input type="search" data-filter-table="%s" '
            'placeholder="%s" style="width:280px;padding:6px 10px;border:1px solid #d1d5db;'
            'border-radius:6px;font-size:13px"></div>'
            '<div id="%s">%s</div>' % (table_id, placeholder, table_id, table_html))


CSS += """
/* 2026-11-04 美化增强 */
table{border-collapse:separate;border-spacing:0;border:1px solid #e5e7eb;border-radius:10px;overflow:hidden}
thead th{background:#f1f5f9;color:#334155;font-weight:600;position:sticky;top:0}
tbody tr:nth-child(even){background:#f8fafc}
tbody tr:hover{background:#eef4ff}
td,th{border-bottom:1px solid #eef2f7}
section{box-shadow:0 1px 3px rgba(15,23,42,.06);border-radius:12px}
.kpi{box-shadow:0 1px 4px rgba(15,23,42,.08);border-radius:12px}
button, a.btn{border-radius:8px}
"""

def render(title, subtitle, meta, banner_html, body_html, footer) -> str:
    """拼完整 HTML 字符串（不落盘）。

    表格排序/搜索脚本默认拼在 body 末尾：飞书预览不执行脚本（表格只是不能点），
    下载后用浏览器打开就能按表头排序、用搜索框筛 SKU/ASIN。
    """
    # 合规扫描：挂在这一层，所有报告自动受检（每个技能各写一份会漏）
    try:
        import compliance as cp
        hits = cp.scan(body_html or "")
        warn = cp.banner_html(hits)
        if warn:
            banner_html = warn + (banner_html or "")
    except Exception:      # 合规扫描失败不该让报告出不来
        pass
    body_html = (body_html or "") + TABLE_JS
    return HTML_SHELL.format(title=title, subtitle=subtitle, meta=meta,
                             css=CSS, banner=banner_html or "", body=body_html,
                             footer=footer)


def save(html_str, path) -> str:
    """落盘（pathlib write_text；父目录自动创建）。返回绝对路径字符串。"""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(html_str, encoding="utf-8")
    return str(p.resolve())
