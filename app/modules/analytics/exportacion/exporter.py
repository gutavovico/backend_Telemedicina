"""Portable report files built without optional PDF/Excel dependencies."""

import csv
import html
import io
import textwrap
import zipfile
from xml.sax.saxutils import escape as xml_escape

from ..reportes.catalog import REPORTS
from ..reportes.schemas import QueryResponse

MIME = {
    "pdf": "application/pdf",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "csv": "text/csv; charset=utf-8",
    "html": "text/html; charset=utf-8",
}
LABELS = {
    "fecha": "Fecha", "id_medico": "Médico ID", "id_especialidad": "Especialidad ID",
    "estado": "Estado", "modalidad": "Modalidad registrada", "encuentros": "Encuentros",
    "citas": "Citas", "cancelaciones": "Cancelaciones", "pacientes_unicos": "Pacientes únicos",
}


def _cell(value) -> str:
    return "" if value is None else str(value)


def _safe_sheet_text(value) -> str:
    text = _cell(value)
    if text.lstrip().startswith(("=", "+", "-", "@", "\t", "\r", "\n")):
        return "'" + text
    return text


def _metadata(result: QueryResponse, clinic_id: int) -> list[tuple[str, str]]:
    definition = result.definicion
    filters = ", ".join(
        f"{item.campo} {item.operador} {_cell(item.valor)}" for item in definition.filtros
    ) or "Ninguno"
    order = ", ".join(f"{item.campo} {item.direccion}" for item in definition.orden) or "Sin agrupación"
    return [
        ("Reporte", REPORTS[definition.reporte].title),
        ("Clínica ID", str(clinic_id)),
        ("Período", f"{definition.periodo.desde.isoformat()} a {definition.periodo.hasta.isoformat()}"),
        ("Filtros", filters),
        ("Columnas", ", ".join(definition.columnas)),
        ("Orden", order),
        ("Generado", result.generado_en.isoformat()),
        ("Semántica", result.semantica),
    ]


def _table(result: QueryResponse) -> list[list[str | int | None]]:
    cols = result.definicion.columnas
    return [[LABELS[name] for name in cols]] + [[row[name] for name in cols] for row in result.filas]


def csv_file(result: QueryResponse, clinic_id: int) -> bytes:
    output = io.StringIO(newline="")
    writer = csv.writer(output)
    for name, value in _metadata(result, clinic_id):
        writer.writerow([name, _safe_sheet_text(value)])
    writer.writerow([])
    for row in _table(result):
        writer.writerow([_safe_sheet_text(value) for value in row])
    return ("\ufeff" + output.getvalue()).encode("utf-8")


def html_file(result: QueryResponse, clinic_id: int) -> bytes:
    meta = "".join(
        f"<dt>{html.escape(name)}</dt><dd>{html.escape(value)}</dd>"
        for name, value in _metadata(result, clinic_id)
    )
    rows = _table(result)
    header = "".join(f"<th scope='col'>{html.escape(_cell(value))}</th>" for value in rows[0])
    body = "".join(
        "<tr>" + "".join(f"<td>{html.escape(_cell(value))}</td>" for value in row) + "</tr>"
        for row in rows[1:]
    )
    document = (
        "<!doctype html><html lang='es'><head><meta charset='utf-8'>"
        "<title>Reporte clínico</title><style>body{font:14px Arial,sans-serif;margin:2rem}"
        "dt{font-weight:bold}dd{margin:0 0 .5rem}table{border-collapse:collapse;width:100%}"
        "th,td{border:1px solid #888;padding:.4rem;text-align:left}</style></head><body>"
        f"<h1>{html.escape(REPORTS[result.definicion.reporte].title)}</h1>"
        f"<dl>{meta}</dl><table><thead><tr>{header}</tr></thead><tbody>{body}</tbody></table>"
        "</body></html>"
    )
    return document.encode("utf-8")


def _excel_column(number: int) -> str:
    name = ""
    while number:
        number, remainder = divmod(number - 1, 26)
        name = chr(65 + remainder) + name
    return name


def xlsx_file(result: QueryResponse, clinic_id: int) -> bytes:
    rows: list[list[str | int | None]] = [[key, value] for key, value in _metadata(result, clinic_id)]
    rows.append([])
    rows.extend(_table(result))
    cells = []
    for row_number, row in enumerate(rows, start=1):
        parts = []
        for col_number, value in enumerate(row, start=1):
            ref = f"{_excel_column(col_number)}{row_number}"
            if type(value) is int:
                parts.append(f'<c r="{ref}" t="n"><v>{value}</v></c>')
            else:
                safe = xml_escape(_safe_sheet_text(value))
                parts.append(f'<c r="{ref}" t="inlineStr"><is><t xml:space="preserve">{safe}</t></is></c>')
        cells.append(f'<row r="{row_number}">{"".join(parts)}</row>')
    sheet = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        f'<sheetData>{"".join(cells)}</sheetData></worksheet>'
    )
    package = {
        "[Content_Types].xml": '<?xml version="1.0" encoding="UTF-8"?>'
            '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
            '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
            '<Default Extension="xml" ContentType="application/xml"/>'
            '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
            '<Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
            '</Types>',
        "_rels/.rels": '<?xml version="1.0" encoding="UTF-8"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>'
            '</Relationships>',
        "xl/workbook.xml": '<?xml version="1.0" encoding="UTF-8"?>'
            '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
            'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
            '<sheets><sheet name="Reporte" sheetId="1" r:id="rId1"/></sheets></workbook>',
        "xl/_rels/workbook.xml.rels": '<?xml version="1.0" encoding="UTF-8"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>'
            '</Relationships>',
        "xl/worksheets/sheet1.xml": sheet,
    }
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, contents in package.items():
            archive.writestr(name, contents)
    return output.getvalue()


def _pdf_hex(value: str) -> str:
    return value.encode("cp1252", errors="replace").hex().upper()


def _pdf_text(x: float, y: float, value: str, size: int = 9, bold: bool = False) -> str:
    font = "F2" if bold else "F1"
    return f"BT /{font} {size} Tf {x:.1f} {y:.1f} Td <{_pdf_hex(value)}> Tj ET"


def _wrap(value: str, width: int) -> list[str]:
    text = _cell(value).replace("\r", " ").replace("\n", " ")
    return textwrap.wrap(text, width=width, break_long_words=True, break_on_hyphens=False) or [""]


def pdf_file(result: QueryResponse, clinic_id: int) -> bytes:
    # A4 landscape. Max six columns means each has at least 120 pt.
    page_width, page_height, margin = 842, 595, 36
    columns = result.definicion.columnas
    table = _table(result)
    cell_width = (page_width - 2 * margin) / len(columns)
    font_size, line_height = 8, 12
    pad_x, pad_top, pad_bottom = 6, 6, 6
    bottom_limit = margin + 6  # Keep the table clear of the page number.
    # Helvetica-Bold at 8 pt has glyphs up to about 7.6 pt wide.
    char_width = max(1, int((cell_width - 2 * pad_x) / 7.6))
    metadata_width = max(1, int((page_width - 2 * margin) / 7.6))
    pages: list[list[str]] = []
    ops: list[str] = []
    y = 0.0

    def start_page() -> None:
        nonlocal ops, y
        ops = ["0 0 0 rg"]
        pages.append(ops)
        y = page_height - margin
        ops.append(_pdf_text(margin, y, REPORTS[result.definicion.reporte].title, 16, True))
        y -= 22
        for name, value in _metadata(result, clinic_id):
            for line in _wrap(f"{name}: {value}", metadata_width):
                ops.append(_pdf_text(margin, y, line, 8))
                y -= 10
        y -= 12
        draw_row(table[0], header=True)

    def draw_row(row: list, *, header: bool = False) -> None:
        nonlocal y
        wrapped = [_wrap(_cell(value), char_width) for value in row]
        total_lines = max(len(lines) for lines in wrapped)
        offset = 0
        while offset < total_lines:
            lines_fit = int((y - bottom_limit - pad_top - pad_bottom) // line_height)
            if lines_fit < 1:
                if header:
                    raise ValueError("El encabezado PDF no cabe en la página")
                start_page()
                continue
            count = min(total_lines - offset, lines_fit)
            height = pad_top + count * line_height + pad_bottom
            bottom = y - height
            if header:
                ops.append(
                    f"0.87 0.91 0.97 rg {margin:.1f} {bottom:.1f} "
                    f"{page_width - 2 * margin:.1f} {height:.1f} re f 0 0 0 rg"
                )
            baseline = y - pad_top - font_size
            for index, lines in enumerate(wrapped):
                x = margin + index * cell_width + pad_x
                for line_index, line in enumerate(lines[offset:offset + count]):
                    ops.append(_pdf_text(x, baseline - line_index * line_height, line, font_size, header))
            ops.append(
                f"0.7 G 0.35 w {margin:.1f} {bottom:.1f} m "
                f"{page_width - margin:.1f} {bottom:.1f} l S 0 G"
            )
            y = bottom
            offset += count
            if offset < total_lines:
                start_page()

    start_page()
    for row in table[1:]:
        draw_row(row)
    if not result.filas:
        ops.append(_pdf_text(margin + 4, y - 10, "Sin registros para los filtros indicados", 9))

    objects: list[bytes] = [b"", b""]  # catalog, pages root
    objects.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>")
    objects.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold /Encoding /WinAnsiEncoding >>")
    page_ids = []
    for number, operations in enumerate(pages, start=1):
        operations.append(_pdf_text(page_width - 100, margin - 12, f"Página {number}", 8))
        stream = "\n".join(operations).encode("ascii")
        content_id = len(objects) + 1
        objects.append(f"<< /Length {len(stream)} >>\nstream\n".encode("ascii") + stream + b"\nendstream")
        page_id = len(objects) + 1
        page_ids.append(page_id)
        objects.append(
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 {page_width} {page_height}] "
            f"/Resources << /Font << /F1 3 0 R /F2 4 0 R >> >> /Contents {content_id} 0 R >>".encode("ascii")
        )
    objects[0] = b"<< /Type /Catalog /Pages 2 0 R >>"
    kids = " ".join(f"{page_id} 0 R" for page_id in page_ids)
    objects[1] = f"<< /Type /Pages /Kids [{kids}] /Count {len(page_ids)} >>".encode("ascii")
    output = io.BytesIO()
    output.write(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets = [0]
    for index, body in enumerate(objects, start=1):
        offsets.append(output.tell())
        output.write(f"{index} 0 obj\n".encode("ascii") + body + b"\nendobj\n")
    start_xref = output.tell()
    output.write(f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode("ascii"))
    for offset in offsets[1:]:
        output.write(f"{offset:010d} 00000 n \n".encode("ascii"))
    output.write(
        f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{start_xref}\n%%EOF\n".encode("ascii")
    )
    return output.getvalue()


BUILDERS = {"pdf": pdf_file, "xlsx": xlsx_file, "csv": csv_file, "html": html_file}
