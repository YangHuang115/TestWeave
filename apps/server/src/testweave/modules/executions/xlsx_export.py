"""无第三方依赖的最小 Excel (.xlsx) 生成器。

用于 M06 执行结果导出。生成的文件符合 Office Open XML Spreadsheet 规范，
可被 Excel / WPS / LibreOffice 正常打开。

安全：所有写入单元格的字符串都会做公式注入防护——以 = + - @ 开头的文本
会被前置单引号转义，避免恶意内容被电子表格软件当成公式执行。
"""

from __future__ import annotations

import io
import zipfile
from typing import Any
from xml.sax.saxutils import escape

# Excel 公式注入危险前缀
_FORMULA_PREFIXES = ("=", "+", "-", "@")


def _escape_cell_text(value: str) -> str:
    text = str(value)
    if text and text[0] in _FORMULA_PREFIXES:
        text = "'" + text
    return escape(text)


def _col_letter(idx: int) -> str:
    """0-based 列索引 -> A, B, ..., Z, AA ..."""
    letters = ""
    idx += 1
    while idx > 0:
        idx, rem = divmod(idx - 1, 26)
        letters = chr(65 + rem) + letters
    return letters


def _render_sheet(rows: list[list[Any]]) -> str:
    parts: list[str] = [
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>',
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">',
        "<sheetData>",
    ]
    for r_idx, row in enumerate(rows, start=1):
        parts.append(f'<row r="{r_idx}">')
        for c_idx, cell in enumerate(row):
            ref = f"{_col_letter(c_idx)}{r_idx}"
            if isinstance(cell, bool):
                text = _escape_cell_text(str(cell))
                parts.append(
                    f'<c r="{ref}" t="inlineStr"><is><t xml:space="preserve">{text}</t></is></c>'
                )
            elif isinstance(cell, (int, float)):
                parts.append(f'<c r="{ref}"><v>{cell}</v></c>')
            else:
                text = "" if cell is None else _escape_cell_text(cell)
                parts.append(
                    f'<c r="{ref}" t="inlineStr"><is><t xml:space="preserve">{text}</t></is></c>'
                )
        parts.append("</row>")
    parts.append("</sheetData>")
    parts.append("</worksheet>")
    return "".join(parts)


def build_xlsx(sheets: list[dict[str, Any]]) -> bytes:
    """生成 xlsx 字节流。

    sheets: [{"name": str, "rows": [[cell, ...], ...]}, ...]
    每个 cell 可为 str / int / float / None / bool。
    """
    if not sheets:
        sheets = [{"name": "Sheet1", "rows": [[""]]}]

    content_types = [
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>',
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">',
        '<Default Extension="rels" '
        'ContentType="application/vnd.openxmlformats-package.relationships+xml"/>',
        '<Default Extension="xml" ContentType="application/xml"/>',
        '<Override PartName="/xl/workbook.xml" '
        'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>',
    ]
    for i in range(len(sheets)):
        content_types.append(
            f'<Override PartName="/xl/worksheets/sheet{i + 1}.xml" '
            'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
        )
    content_types.append("</Types>")

    root_rels = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" '
        'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" '
        'Target="xl/workbook.xml"/>'
        "</Relationships>"
    )

    sheet_tags = []
    sheet_rels = []
    for i, sh in enumerate(sheets):
        name = (sh.get("name") or f"Sheet{i + 1}")[:31]
        sheet_tags.append(f'<sheet name="{escape(name)}" sheetId="{i + 1}" r:id="rId{i + 1}"/>')
        sheet_rels.append(
            f'<Relationship Id="rId{i + 1}" '
            'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" '
            f'Target="worksheets/sheet{i + 1}.xml"/>'
        )
    workbook = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
        "<sheets>" + "".join(sheet_tags) + "</sheets>"
        "</workbook>"
    )
    workbook_rels = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        + "".join(sheet_rels)
        + "</Relationships>"
    )

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("[Content_Types].xml", "".join(content_types))
        zf.writestr("_rels/.rels", root_rels)
        zf.writestr("xl/workbook.xml", workbook)
        zf.writestr("xl/_rels/workbook.xml.rels", workbook_rels)
        for i, sh in enumerate(sheets):
            zf.writestr(f"xl/worksheets/sheet{i + 1}.xml", _render_sheet(sh.get("rows", [])))
    return buffer.getvalue()
