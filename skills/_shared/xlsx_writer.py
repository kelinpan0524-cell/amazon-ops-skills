#!/usr/bin/env python3
"""极简 xlsx 写出器（仅用标准库）：供广告全量明细等大表归档 Excel 用。

不引入 openpyxl——仓库 CI 要在无第三方依赖的干净机器上跑。
单工作表、inline 字符串，数字按数值写，Excel/WPS/飞书预览均可打开。
"""
import zipfile
from xml.sax.saxutils import escape


def _col(n):
    s = ""
    while n > 0:
        n, r = divmod(n - 1, 26)
        s = chr(65 + r) + s
    return s


def _is_num(v):
    if isinstance(v, bool) or v is None:
        return False
    if isinstance(v, (int, float)):
        return True
    if isinstance(v, str):
        try:
            float(v)
            return v.strip() != "" and not v.startswith("0")
        except ValueError:
            return False
    return False


def write_xlsx(path, headers, rows, sheet_name="data"):
    rows = list(rows)
    xml = ['<?xml version="1.0" encoding="UTF-8" standalone="yes"?>',
           '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">',
           '<sheetData>']
    all_rows = [list(headers)] + [list(r) for r in rows]
    for ri, row in enumerate(all_rows, 1):
        xml.append('<row r="%d">' % ri)
        for ci, v in enumerate(row, 1):
            ref = "%s%d" % (_col(ci), ri)
            if v is None:
                continue
            if ri > 1 and _is_num(v):
                xml.append('<c r="%s"><v>%s</v></c>' % (ref, v))
            else:
                xml.append('<c r="%s" t="inlineStr"><is><t xml:space="preserve">%s</t></is></c>'
                           % (ref, escape(str(v))))
        xml.append("</row>")
    xml.append("</sheetData></worksheet>")
    sheet = "".join(xml)
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml",
                   '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                   '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
                   '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
                   '<Default Extension="xml" ContentType="application/xml"/>'
                   '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
                   '<Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
                   '</Types>')
        z.writestr("_rels/.rels",
                   '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                   '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                   '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>'
                   '</Relationships>')
        z.writestr("xl/workbook.xml",
                   '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                   '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
                   'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
                   '<sheets><sheet name="%s" sheetId="1" r:id="rId1"/></sheets></workbook>' % escape(sheet_name))
        z.writestr("xl/_rels/workbook.xml.rels",
                   '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                   '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                   '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>'
                   '</Relationships>')
        z.writestr("xl/worksheets/sheet1.xml", sheet)
    return path
