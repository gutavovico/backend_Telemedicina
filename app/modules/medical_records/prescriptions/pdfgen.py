"""Generador PDF puro en Python estándar (sin dependencias externas).

Produce un PDF 1.4 determinista (mismos bytes ante mismos datos) con la
receta médica digital y el QR de validación embebido como rectángulos
vectoriales. El SHA-256 de estos bytes es `recetas.hash_pdf` y debe
coincidir con `documentos_clinicos.hash_archivo` (diseño decisión 2).
"""
import hashlib
from dataclasses import dataclass, field
from typing import List, Optional


PAGE_WIDTH, PAGE_HEIGHT = 595, 842  # A4 en puntos
MARGIN = 50
CONTENT_TOP = 782
CONTENT_BOTTOM = 60


@dataclass
class RecetaPdfDetalle:
    nombre: str
    principio_activo: Optional[str] = None
    concentracion: Optional[str] = None
    forma_farmaceutica: Optional[str] = None
    dosis: str = ""
    frecuencia: str = ""
    duracion: str = ""
    via_administracion: str = ""
    cantidad: int = 0
    indicaciones: Optional[str] = None


@dataclass
class RecetaPdfData:
    clinica_nombre: str
    folio: str
    fecha_emision: str
    fecha_vencimiento: str
    paciente_nombre: str
    medico_nombre: str
    medico_matricula: str
    medico_especialidad: str
    id_consulta: int
    indicaciones_generales: Optional[str] = None
    detalles: List[RecetaPdfDetalle] = field(default_factory=list)
    algoritmo_firma: str = "ED25519"
    key_id: str = ""
    firma_digital: str = ""
    validation_url: str = ""
    qr_matrix: List[List[bool]] = field(default_factory=list)


_TRANSLATIONS = {
    "—": "-", "–": "-", "•": "-", "“": '"', "”": '"',
    "‘": "'", "’": "'", "…": "...", "°": "o",
}


def _to_latin1(text: str) -> str:
    out = []
    for ch in str(text or ""):
        ch = _TRANSLATIONS.get(ch, ch)
        try:
            ch.encode("latin-1")
            out.append(ch)
        except UnicodeEncodeError:
            out.append("?")
    return "".join(out)


def _escape(text: str) -> str:
    return _to_latin1(text).replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def _wrap(text: str, max_chars: int):
    words = _to_latin1(text).split()
    lines, current = [], ""
    for word in words:
        while len(word) > max_chars:
            if current:
                lines.append(current)
                current = ""
            lines.append(word[:max_chars])
            word = word[max_chars:]
        candidate = (current + " " + word).strip()
        if len(candidate) <= max_chars:
            current = candidate
        else:
            if current:
                lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines or [""]


class _PageBuilder:
    def __init__(self):
        self.ops = []
        self.y = CONTENT_TOP

    def _ensure_space(self, needed: float) -> bool:
        return self.y - needed >= CONTENT_BOTTOM

    def text(self, text: str, size: int = 10, bold: bool = False, indent: int = 0):
        for line in _wrap(text, 95 if size >= 10 else 110):
            if not self._ensure_space(size + 4):
                return False
            font = "F2" if bold else "F1"
            self.ops.append(
                f"BT /{font} {size} Tf {MARGIN + indent} {self.y:.1f} Td ({_escape(line)}) Tj ET"
            )
            self.y -= size + 4
        return True

    def blank(self, points: float = 6):
        self.y -= points

    def rule(self):
        if not self._ensure_space(10):
            return False
        self.ops.append(
            f"0.6 w 0.5 0.5 0.5 RG {MARGIN} {self.y:.1f} {PAGE_WIDTH - 2 * MARGIN} 0 re S"
        )
        self.y -= 10
        return True

    def qr(self, matrix, box_size: float = 130):
        """Dibuja el QR con fondo blanco y módulos oscuros como rectángulos."""
        n = len(matrix)
        if n == 0:
            return True
        if not self._ensure_space(box_size + 30):
            return False
        x0 = PAGE_WIDTH - MARGIN - box_size
        y0 = self.y - box_size
        cell = box_size / n
        self.ops.append(f"1 1 1 rg {x0:.2f} {y0:.2f} {box_size:.2f} {box_size:.2f} re f")
        self.ops.append("0 0 0 rg")
        for row in range(n):
            for col in range(n):
                if matrix[row][col]:
                    x = x0 + col * cell
                    y = y0 + (n - 1 - row) * cell
                    self.ops.append(f"{x:.2f} {y:.2f} {cell + 0.05:.2f} {cell + 0.05:.2f} re f")
        self.y = y0 - 16
        return True


def _build_pages(data: RecetaPdfData):
    pages = []
    current = _PageBuilder()

    def new_page():
        pages.append(current)
        return _PageBuilder()

    def emit(text, **kwargs):
        nonlocal current
        if not current.text(text, **kwargs):
            current = new_page()
            assert current.text(text, **kwargs)

    def emit_rule():
        nonlocal current
        if not current.rule():
            current = new_page()
            current.rule()

    emit(data.clinica_nombre, size=16, bold=True)
    emit("RECETA MEDICA DIGITAL", size=13, bold=True)
    emit(f"Folio: {data.folio}", size=11, bold=True)
    current.blank(4)
    emit_rule()
    emit("Paciente", size=11, bold=True)
    emit(data.paciente_nombre, size=10)
    current.blank(2)
    emit("Medico emisor", size=11, bold=True)
    emit(f"{data.medico_nombre} - Mat. {data.medico_matricula} ({data.medico_especialidad})", size=10)
    current.blank(2)
    emit(f"Consulta: {data.id_consulta}   Emision: {data.fecha_emision}   Vencimiento: {data.fecha_vencimiento}", size=10)
    current.blank(4)
    emit_rule()
    emit("Medicamentos prescritos", size=11, bold=True)
    for idx, det in enumerate(data.detalles, start=1):
        compuesto = det.nombre
        extras = " / ".join(p for p in [det.principio_activo, det.concentracion, det.forma_farmaceutica] if p)
        if extras:
            compuesto += f" ({extras})"
        emit(f"{idx}. {compuesto}", size=10, bold=True)
        emit(f"Posologia: {det.dosis} - {det.frecuencia} - {det.duracion} - Via {det.via_administracion} - Cantidad: {det.cantidad}", size=9, indent=12)
        if det.indicaciones:
            emit(f"Indicaciones: {det.indicaciones}", size=9, indent=12)
        current.blank(2)
    if data.indicaciones_generales:
        current.blank(2)
        emit("Indicaciones generales", size=11, bold=True)
        emit(data.indicaciones_generales, size=10)
    current.blank(4)
    emit_rule()
    emit("Firma digital", size=11, bold=True)
    emit(f"Algoritmo: {data.algoritmo_firma}   Key ID: {data.key_id}", size=9)
    firma = _to_latin1(data.firma_digital)
    for i in range(0, len(firma), 100):
        emit(firma[i:i + 100], size=8)
    current.blank(4)
    emit("Validacion publica", size=11, bold=True)
    emit(data.validation_url, size=9)
    if not current.qr(data.qr_matrix):
        current = new_page()
        emit("Validacion publica (continuacion)", size=11, bold=True)
        emit(data.validation_url, size=9)
        assert current.qr(data.qr_matrix)
    pages.append(current)
    return pages


def build_receta_pdf(data: RecetaPdfData) -> bytes:
    """Construye el PDF definitivo de la receta y devuelve sus bytes."""
    pages = _build_pages(data)

    objects = []
    # 1: catálogo, 2: páginas, 3..: página + contenido por hoja, luego fuentes
    num_pages = len(pages)
    page_obj_nums = []
    content_obj_nums = []
    next_num = 3
    for _ in pages:
        page_obj_nums.append(next_num)
        content_obj_nums.append(next_num + 1)
        next_num += 2
    font_regular_num = next_num
    font_bold_num = next_num + 1

    objects.append((1, "<< /Type /Catalog /Pages 2 0 R >>"))
    kids = " ".join(f"{n} 0 R" for n in page_obj_nums)
    objects.append((2, f"<< /Type /Pages /Kids [{kids}] /Count {num_pages} >>"))
    for page_num, content_num, builder in zip(page_obj_nums, content_obj_nums, pages):
        objects.append((
            page_num,
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 {PAGE_WIDTH} {PAGE_HEIGHT}] "
            f"/Resources << /Font << /F1 {font_regular_num} 0 R /F2 {font_bold_num} 0 R >> >> "
            f"/Contents {content_num} 0 R >>",
        ))
        stream = "\n".join(builder.ops).encode("latin-1")
        objects.append((content_num, None, stream))
    objects.append((font_regular_num, "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>"))
    objects.append((font_bold_num, "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold /Encoding /WinAnsiEncoding >>"))

    info_text = _escape(f"Receta {data.folio}")
    info_num = font_bold_num + 1
    objects.append((info_num, f"<< /Title ({info_text}) /Creator (Telemedicina CU16) /CreationDate (D:20260101000000Z) >>"))

    out = bytearray()
    out += b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n"
    offsets = {}
    for item in objects:
        num = item[0]
        offsets[num] = len(out)
        out += f"{num} 0 obj\n".encode("ascii")
        if len(item) == 3:
            _, _, stream = item
            out += f"<< /Length {len(stream)} >>\nstream\n".encode("ascii")
            out += stream + b"\nendstream\n"
        else:
            out += item[1].encode("latin-1") + b"\n"
        out += b"endobj\n"
    xref_pos = len(out)
    max_num = max(offsets)
    out += f"xref\n0 {max_num + 1}\n".encode("ascii")
    out += b"0000000000 65535 f \n"
    for num in range(1, max_num + 1):
        out += f"{offsets.get(num, 0):010d} 00000 n \n".encode("ascii")
    doc_id = hashlib.sha256(bytes(out)).hexdigest()[:32]
    out += (
        f"trailer\n<< /Size {max_num + 1} /Root 1 0 R /Info {info_num} 0 R "
        f"/ID [<{doc_id}><{doc_id}>] >>\nstartxref\n{xref_pos}\n%%EOF"
    ).encode("ascii")
    return bytes(out)
