from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse, RedirectResponse
from sqlalchemy.orm import Session
from io import BytesIO
from datetime import datetime, date
import os
import re
import json

from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from reportlab.lib.colors import HexColor
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.graphics.barcode.qr import QrCodeWidget
from reportlab.graphics.shapes import Drawing
from reportlab.graphics import renderPDF

from ..database import get_db
from ..models import Doctor, Patient, Encounter, ClinicalNote, EncounterEvolution
from .auth import get_logged_doctor

router = APIRouter(tags=["PDF"])

BRAND_NAME = "NexaCenter"
LOGO_FILENAME = "logo.png"

COLOR_PRIMARY = HexColor("#0B4DBB")
COLOR_PRIMARY_SOFT = HexColor("#EAF2FF")
COLOR_TEXT = HexColor("#1F2937")
COLOR_MUTED = HexColor("#6B7280")
COLOR_BORDER = HexColor("#D9E3F0")
COLOR_BG = HexColor("#F8FBFF")
COLOR_WHITE = HexColor("#FFFFFF")
COLOR_WATERMARK = HexColor("#E8EEF8")
COLOR_QR_LABEL = HexColor("#4B5563")

PAGE_SIZE = A4
PAGE_WIDTH, PAGE_HEIGHT = PAGE_SIZE

LEFT = 42
RIGHT = 42
TOP = 42
BOTTOM = 34
CONTENT_WIDTH = PAGE_WIDTH - LEFT - RIGHT

KNOWN_DOCTORS = {
    "Dra. Yiria Rosario Collantes Santos": {
        "registration": "1312059627",
        "specialty": "Médico General",
    },
    "Dr. Miguel Andrés Herrería Rodríguez": {
        "registration": "1750785220",
        "specialty": "Médico Cirujano",
    },
}


def _require_login(request: Request, db: Session):
    doctor = get_logged_doctor(request, db)
    if not doctor:
        return None
    return doctor


def _redirect_login():
    return RedirectResponse(url="/login", status_code=302)


def _asset_path(*parts: str) -> str:
    base = os.path.dirname(os.path.dirname(__file__))
    return os.path.join(base, "assets", *parts)


def _best_datetime(enc: Encounter):
    for attr in ("ended_at", "encounter_date", "date", "start_time", "created_at", "updated_at"):
        if hasattr(enc, attr):
            val = getattr(enc, attr)
            if val is not None:
                return val
    return None


def _fmt_dt(val) -> str:
    if val is None:
        return "-"
    try:
        return val.strftime("%Y-%m-%d %H:%M")
    except Exception:
        return str(val)


def _safe(value, fallback="-"):
    if value is None:
        return fallback
    text = str(value).strip()
    return text if text else fallback


def _slugify(value: str) -> str:
    value = (value or "").strip().lower()
    value = re.sub(r"[^a-z0-9]+", "_", value)
    return value.strip("_")


def _doctor_meta(doctor: Doctor | None):
    name = getattr(doctor, "name", None) if doctor else None
    specialty = getattr(doctor, "specialty", None) if doctor else None
    registration = getattr(doctor, "registration", None) if doctor else None

    if name and (not specialty or not registration):
        kb = KNOWN_DOCTORS.get(name)
        if kb:
            specialty = specialty or kb.get("specialty")
            registration = registration or kb.get("registration")

    return (name or "-", specialty or "-", registration or "-")


def _doctor_signature_path(doctor: Doctor | None) -> str | None:
    if not doctor:
        return None

    reg = getattr(doctor, "registration", None)
    doc_id = getattr(doctor, "id", None)
    name = getattr(doctor, "name", None)

    candidates = []
    if reg:
        candidates.extend([
            _asset_path("signatures", f"{reg}.png"),
            _asset_path("signatures", f"{reg}.jpg"),
            _asset_path("signatures", f"doctor_{reg}.png"),
            _asset_path("signatures", f"doctor_{reg}.jpg"),
        ])
    if doc_id:
        candidates.extend([
            _asset_path("signatures", f"doctor_{doc_id}.png"),
            _asset_path("signatures", f"doctor_{doc_id}.jpg"),
        ])
    if name:
        slug = _slugify(name)
        candidates.extend([
            _asset_path("signatures", f"{slug}.png"),
            _asset_path("signatures", f"{slug}.jpg"),
        ])

    for path in candidates:
        if os.path.exists(path):
            return path
    return None


def _doctor_stamp_path(doctor: Doctor | None) -> str | None:
    if not doctor:
        return None

    reg = getattr(doctor, "registration", None)
    doc_id = getattr(doctor, "id", None)
    name = getattr(doctor, "name", None)

    candidates = []
    if reg:
        candidates.extend([
            _asset_path("stamps", f"{reg}.png"),
            _asset_path("stamps", f"{reg}.jpg"),
            _asset_path("stamps", f"stamp_{reg}.png"),
            _asset_path("stamps", f"stamp_{reg}.jpg"),
        ])
    if doc_id:
        candidates.extend([
            _asset_path("stamps", f"doctor_{doc_id}.png"),
            _asset_path("stamps", f"doctor_{doc_id}.jpg"),
        ])
    if name:
        slug = _slugify(name)
        candidates.extend([
            _asset_path("stamps", f"{slug}.png"),
            _asset_path("stamps", f"{slug}.jpg"),
        ])

    for path in candidates:
        if os.path.exists(path):
            return path
    return None


def _wrap_text(text: str, max_width: float, font_name="Helvetica", font_size=10):
    text = (text or "").replace("\r\n", "\n").replace("\r", "\n")
    if not text.strip():
        return ["-"]

    lines = []
    for paragraph in text.split("\n"):
        paragraph = paragraph.strip()
        if not paragraph:
            lines.append("")
            continue

        words = paragraph.split()
        current = ""
        for word in words:
            test = (current + " " + word).strip()
            if stringWidth(test, font_name, font_size) <= max_width:
                current = test
            else:
                if current:
                    lines.append(current)
                current = word
        if current:
            lines.append(current)

    return lines or ["-"]


def _measure_paragraph_height(text: str, max_width: float, font_name="Helvetica", font_size=10, line_gap=4):
    lines = _wrap_text(text, max_width, font_name, font_size)
    line_height = font_size + line_gap
    return max(18, len(lines) * line_height + 10)


def _draw_paragraph(c, x: float, y_top: float, text: str, max_width: float, font_name="Helvetica", font_size=10, color=COLOR_TEXT, line_gap=4):
    lines = _wrap_text(text, max_width, font_name, font_size)
    line_height = font_size + line_gap

    c.setFont(font_name, font_size)
    c.setFillColor(color)

    y = y_top
    for line in lines:
        if line == "":
            y -= line_height * 0.6
        else:
            c.drawString(x, y, line)
            y -= line_height

    return y


def _draw_watermark(c):
    c.saveState()
    c.setFillColor(COLOR_WATERMARK)
    c.setFont("Helvetica-Bold", 56)
    c.translate(PAGE_WIDTH / 2, PAGE_HEIGHT / 2)
    c.rotate(28)
    c.drawCentredString(0, 0, BRAND_NAME.upper())
    c.restoreState()


def _draw_page_footer(c, page_num: int):
    c.setStrokeColor(COLOR_BORDER)
    c.setLineWidth(0.8)
    c.line(LEFT, BOTTOM + 10, PAGE_WIDTH - RIGHT, BOTTOM + 10)

    c.setFont("Helvetica", 8)
    c.setFillColor(COLOR_MUTED)
    c.drawString(LEFT, BOTTOM - 2, "Documento clínico confidencial - NexaCenter")
    c.drawRightString(PAGE_WIDTH - RIGHT, BOTTOM - 2, f"Página {page_num}")


def _draw_page_header(c, title_right: str, subtitle_right: str = ""):
    header_h = 78
    top_y = PAGE_HEIGHT - TOP

    c.setFillColor(COLOR_PRIMARY_SOFT)
    c.roundRect(LEFT, top_y - header_h, CONTENT_WIDTH, header_h, 16, stroke=0, fill=1)

    logo_path = _asset_path(LOGO_FILENAME)
    logo_x = LEFT + 18
    logo_y = top_y - 58

    if os.path.exists(logo_path):
        try:
            img = ImageReader(logo_path)
            iw, ih = img.getSize()
            desired_w = 82
            desired_h = desired_w * (ih / float(iw))
            if desired_h > 42:
                desired_h = 42
                desired_w = desired_h * (iw / float(ih))
            c.drawImage(
                img,
                logo_x,
                logo_y,
                width=desired_w,
                height=desired_h,
                mask="auto",
                preserveAspectRatio=True,
                anchor="sw",
            )
        except Exception:
            c.setFont("Helvetica-Bold", 18)
            c.setFillColor(COLOR_PRIMARY)
            c.drawString(logo_x, top_y - 34, BRAND_NAME)
    else:
        c.setFont("Helvetica-Bold", 18)
        c.setFillColor(COLOR_PRIMARY)
        c.drawString(logo_x, top_y - 34, BRAND_NAME)

    c.setFillColor(COLOR_PRIMARY)
    c.setFont("Helvetica-Bold", 22)
    c.drawRightString(PAGE_WIDTH - RIGHT - 18, top_y - 26, title_right)

    if subtitle_right:
        c.setFont("Helvetica", 9)
        c.setFillColor(COLOR_MUTED)
        c.drawRightString(PAGE_WIDTH - RIGHT - 18, top_y - 42, subtitle_right)

    return top_y - header_h - 18


def _draw_info_chip(c, x: float, y: float, label: str, value: str, width: float):
    h = 22
    c.setFillColor(COLOR_WHITE)
    c.setStrokeColor(COLOR_BORDER)
    c.setLineWidth(0.8)
    c.roundRect(x, y - h, width, h, 10, stroke=1, fill=1)

    label_text = _safe(label, "-")
    value_text = _safe(value, "-")

    c.setFont("Helvetica-Bold", 8)
    c.setFillColor(COLOR_MUTED)
    c.drawString(x + 8, y - 14, label_text)

    c.setFont("Helvetica", 8)
    c.setFillColor(COLOR_TEXT)

    value_x = x + 96
    max_value_width = width - (value_x - x) - 8
    if max_value_width < 30:
        max_value_width = 30

    while stringWidth(value_text, "Helvetica", 8) > max_value_width and len(value_text) > 3:
        value_text = value_text[:-4] + "..."

    c.drawString(value_x, y - 14, value_text)


def _draw_meta_grid(c, y_top: float, rows: list[tuple[str, str]], cols: int = 2):
    gutter = 12
    row_h = 22
    inner_pad = 8
    total_rows = (len(rows) + cols - 1) // cols
    box_h = 22 + (total_rows * row_h) + 12

    c.setFillColor(COLOR_WHITE)
    c.setStrokeColor(COLOR_BORDER)
    c.setLineWidth(0.9)
    c.roundRect(LEFT, y_top - box_h, CONTENT_WIDTH, box_h, 14, stroke=1, fill=1)

    usable_w = CONTENT_WIDTH - inner_pad * 2
    col_w = (usable_w - gutter * (cols - 1)) / cols

    y = y_top - 18
    value_offset = 104

    for idx, (label, value) in enumerate(rows):
        col = idx % cols
        row = idx // cols

        x = LEFT + inner_pad + col * (col_w + gutter)
        yy = y - row * row_h

        label_text = f"{label}:"
        value_text = _safe(value)

        c.setFont("Helvetica-Bold", 8)
        c.setFillColor(COLOR_MUTED)
        c.drawString(x, yy, label_text)

        c.setFont("Helvetica", 8.5)
        c.setFillColor(COLOR_TEXT)

        max_value_width = col_w - value_offset - 4
        if max_value_width < 40:
            max_value_width = 40

        while stringWidth(value_text, "Helvetica", 8.5) > max_value_width and len(value_text) > 3:
            value_text = value_text[:-4] + "..."

        c.drawString(x + value_offset, yy, value_text)

    return y_top - box_h - 14


def _section_height(title: str, text: str):
    title_h = 28
    body_h = _measure_paragraph_height(text, CONTENT_WIDTH - 24, "Helvetica", 10, 4)
    return title_h + body_h + 18


def _draw_section_card(c, y_top: float, title: str, text: str):
    card_h = _section_height(title, text)

    c.setFillColor(COLOR_WHITE)
    c.setStrokeColor(COLOR_BORDER)
    c.setLineWidth(0.9)
    c.roundRect(LEFT, y_top - card_h, CONTENT_WIDTH, card_h, 14, stroke=1, fill=1)

    c.setFillColor(COLOR_PRIMARY_SOFT)
    c.roundRect(LEFT + 1, y_top - 32, CONTENT_WIDTH - 2, 31, 14, stroke=0, fill=1)

    c.setFillColor(COLOR_PRIMARY)
    c.setFont("Helvetica-Bold", 11)
    c.drawString(LEFT + 14, y_top - 20, title)

    text_top = y_top - 46
    _draw_paragraph(
        c,
        LEFT + 12,
        text_top,
        _safe(text, "-"),
        CONTENT_WIDTH - 24,
        "Helvetica",
        10,
        COLOR_TEXT,
        4,
    )

    return y_top - card_h - 12


def _draw_vitals_card(c, y_top: float, note: ClinicalNote | None):
    card_h = 76

    c.setFillColor(COLOR_WHITE)
    c.setStrokeColor(COLOR_BORDER)
    c.setLineWidth(0.9)
    c.roundRect(LEFT, y_top - card_h, CONTENT_WIDTH, card_h, 14, stroke=1, fill=1)

    c.setFillColor(COLOR_PRIMARY_SOFT)
    c.roundRect(LEFT + 1, y_top - 32, CONTENT_WIDTH - 2, 31, 14, stroke=0, fill=1)

    c.setFillColor(COLOR_PRIMARY)
    c.setFont("Helvetica-Bold", 11)
    c.drawString(LEFT + 14, y_top - 20, "Signos vitales")

    ta_value = "-"
    if note and (note.ta_sys is not None or note.ta_dia is not None):
        ta_value = f"{_safe(note.ta_sys, '')}/{_safe(note.ta_dia, '')}"

    items = [
        ("TA", ta_value),
        ("FC", _safe(getattr(note, "hr", None))),
        ("FR", _safe(getattr(note, "rr", None))),
        ("SpO2", _safe(getattr(note, "spo2", None))),
        ("Temp", _safe(getattr(note, "temp", None))),
    ]

    inner_x = LEFT + 12
    inner_y = y_top - 40
    gap = 8
    box_w = (CONTENT_WIDTH - 24 - gap * 4) / 5

    for idx, (label, value) in enumerate(items):
        x = inner_x + idx * (box_w + gap)
        c.setFillColor(COLOR_BG)
        c.setStrokeColor(COLOR_BORDER)
        c.roundRect(x, inner_y - 24, box_w, 24, 8, stroke=1, fill=1)

        c.setFont("Helvetica-Bold", 8)
        c.setFillColor(COLOR_MUTED)
        c.drawString(x + 8, inner_y - 15, label)

        c.setFont("Helvetica", 8)
        c.setFillColor(COLOR_TEXT)
        c.drawRightString(x + box_w - 8, inner_y - 15, _safe(value))

    return y_top - card_h - 12


def _build_validation_url(request: Request, enc: Encounter) -> str:
    base = str(request.base_url).rstrip("/")
    return f"{base}/app/encounters/{enc.id}"


def _draw_qr(c, qr_text: str, x: float, y: float, size: float = 70):
    qr = QrCodeWidget(qr_text)
    bounds = qr.getBounds()
    w = bounds[2] - bounds[0]
    h = bounds[3] - bounds[1]
    drawing = Drawing(size, size, transform=[size / w, 0, 0, size / h, 0, 0])
    drawing.add(qr)
    renderPDF.draw(drawing, c, x, y)


def _draw_signature_image(c, img_path: str, x: float, y: float, max_w: float, max_h: float):
    try:
        img = ImageReader(img_path)
        iw, ih = img.getSize()
        scale = min(max_w / float(iw), max_h / float(ih))
        draw_w = iw * scale
        draw_h = ih * scale
        c.drawImage(
            img,
            x,
            y,
            width=draw_w,
            height=draw_h,
            mask="auto",
            preserveAspectRatio=True,
            anchor="sw",
        )
    except Exception:
        pass


def _draw_signature_block(c, y_top: float, attending_doctor: Doctor | None, qr_text: str):
    name, specialty, registration = _doctor_meta(attending_doctor)
    signature_path = _doctor_signature_path(attending_doctor)
    stamp_path = _doctor_stamp_path(attending_doctor)
    box_h = 136

    c.setFillColor(COLOR_WHITE)
    c.setStrokeColor(COLOR_BORDER)
    c.setLineWidth(0.9)
    c.roundRect(LEFT, y_top - box_h, CONTENT_WIDTH, box_h, 14, stroke=1, fill=1)

    c.setFillColor(COLOR_PRIMARY_SOFT)
    c.roundRect(LEFT + 1, y_top - 32, CONTENT_WIDTH - 2, 31, 14, stroke=0, fill=1)

    c.setFillColor(COLOR_PRIMARY)
    c.setFont("Helvetica-Bold", 11)
    c.drawString(LEFT + 14, y_top - 20, "Validación profesional")

    body_top = y_top - 44

    left_x = LEFT + 14
    c.setFont("Helvetica", 9)
    c.setFillColor(COLOR_MUTED)
    c.drawString(left_x, body_top, "Firma del profesional")

    line_y = body_top - 18
    c.setStrokeColor(COLOR_MUTED)
    c.setLineWidth(0.8)
    c.line(left_x, line_y, left_x + 250, line_y)

    if signature_path:
        _draw_signature_image(c, signature_path, left_x + 20, line_y - 6, 150, 34)
    else:
        c.setFont("Helvetica-Oblique", 8)
        c.setFillColor(COLOR_MUTED)
        c.drawString(left_x + 18, line_y + 8, "Firma digital / manuscrita")

    c.setFont("Helvetica", 9)
    c.setFillColor(COLOR_MUTED)
    c.drawString(left_x, body_top - 40, "Nombre:")
    c.drawString(left_x, body_top - 56, "Especialidad:")
    c.drawString(left_x, body_top - 72, "Registro profesional:")

    c.setFont("Helvetica", 9)
    c.setFillColor(COLOR_TEXT)
    c.drawString(left_x + 110, body_top - 40, name)
    c.drawString(left_x + 110, body_top - 56, specialty)
    c.drawString(left_x + 110, body_top - 72, registration)

    stamp_x = LEFT + CONTENT_WIDTH - 255
    stamp_box_y = y_top - 96
    c.setFont("Helvetica", 9)
    c.setFillColor(COLOR_MUTED)
    c.drawString(stamp_x, body_top, "Sello profesional")

    c.setStrokeColor(COLOR_BORDER)
    c.setFillColor(COLOR_BG)
    c.roundRect(stamp_x, stamp_box_y, 98, 54, 10, stroke=1, fill=1)

    if stamp_path:
        _draw_signature_image(c, stamp_path, stamp_x + 8, stamp_box_y + 6, 82, 42)
    else:
        c.setFont("Helvetica-Oblique", 7)
        c.setFillColor(COLOR_MUTED)
        c.drawCentredString(stamp_x + 49, stamp_box_y + 24, "Sello")

    qr_x = LEFT + CONTENT_WIDTH - 132
    qr_y = y_top - 108
    c.setFont("Helvetica", 9)
    c.setFillColor(COLOR_MUTED)
    c.drawString(qr_x, body_top, "QR de validación")
    _draw_qr(c, qr_text, qr_x, qr_y, size=62)

    c.setFont("Helvetica", 7)
    c.setFillColor(COLOR_QR_LABEL)
    c.drawString(qr_x, qr_y - 8, f"ID atención: {registration} / #{getattr(attending_doctor, 'id', '-')}")
    c.drawString(qr_x, qr_y - 18, "Escanee para verificación interna")

    return y_top - box_h - 10


def _ensure_space(c, y: float, needed: float, page_num: int, title: str, subtitle: str):
    if y - needed >= BOTTOM + 20:
        return y, page_num

    c.showPage()
    _draw_watermark(c)
    y = _draw_page_header(c, title, subtitle)
    _draw_page_footer(c, page_num)
    return y, page_num + 1


def _patient_age(patient: Patient | None) -> str:
    birth_date = getattr(patient, "birth_date", None) if patient else None
    if not birth_date:
        return "-"
    try:
        today = date.today()
        years = today.year - birth_date.year - (
            (today.month, today.day) < (birth_date.month, birth_date.day)
        )
        return str(years)
    except Exception:
        return "-"


def _load_prescription_items(enc: Encounter) -> list[dict]:
    raw = getattr(enc, "prescription_json", None)
    if not raw:
        return []

    try:
        items = json.loads(raw)
    except Exception:
        return []

    cleaned = []
    if isinstance(items, list):
        for item in items:
            if not isinstance(item, dict):
                continue

            prescription = str(item.get("prescription") or "").strip()
            indication = str(item.get("indication") or "").strip()

            if prescription or indication:
                cleaned.append(
                    {
                        "prescription": prescription,
                        "indication": indication,
                    }
                )

    return cleaned


def _rx_table_row_height(item: dict) -> float:
    left_h = _measure_paragraph_height(item.get("prescription") or "-", (CONTENT_WIDTH - 32) / 2 - 12, "Helvetica", 10, 3)
    right_h = _measure_paragraph_height(item.get("indication") or "-", (CONTENT_WIDTH - 32) / 2 - 12, "Helvetica", 10, 3)
    return max(34, left_h, right_h) + 8


def _draw_prescription_header(c, enc: Encounter, patient: Patient | None, doctor: Doctor | None):
    y = _draw_page_header(
        c,
        "Receta Médica",
        f"Atención #{enc.id}",
    )

    chip_w = (CONTENT_WIDTH - 16) / 3
    _draw_info_chip(c, LEFT, y, "Fecha prescripción", _fmt_dt(_best_datetime(enc)), chip_w)
    _draw_info_chip(c, LEFT + chip_w + 8, y, "Paciente", getattr(patient, "full_name", None) or "N/A", chip_w)
    _draw_info_chip(c, LEFT + (chip_w + 8) * 2, y, "Documento", datetime.now().strftime("%Y-%m-%d %H:%M"), chip_w)
    y -= 34

    doc_name, doc_spec, doc_reg = _doctor_meta(doctor)
    meta_rows = [
        ("Paciente", getattr(patient, "full_name", None) or "-"),
        ("Cédula", getattr(patient, "cedula", None) or "-"),
        ("Edad", _patient_age(patient)),
        ("Médico tratante", doc_name),
        ("Especialidad", doc_spec),
        ("Registro", doc_reg),
        ("Tipo de consulta", getattr(enc, "visit_type", None) or "-"),
        ("ID atención", str(enc.id)),
    ]
    y = _draw_meta_grid(c, y, meta_rows, cols=2)
    return y


def _draw_prescription_table(c, y_top: float, items: list[dict]):
    header_h = 28

    c.setFillColor(COLOR_PRIMARY_SOFT)
    c.setStrokeColor(COLOR_BORDER)
    c.setLineWidth(0.9)
    c.roundRect(LEFT, y_top - header_h, CONTENT_WIDTH, header_h, 12, stroke=1, fill=1)

    mid_x = LEFT + (CONTENT_WIDTH / 2)

    c.setFont("Helvetica-Bold", 11)
    c.setFillColor(COLOR_PRIMARY)
    c.drawString(LEFT + 14, y_top - 18, "Prescripción")
    c.drawString(mid_x + 10, y_top - 18, "Indicación")

    c.setStrokeColor(COLOR_BORDER)
    c.line(mid_x, y_top - header_h, mid_x, y_top)

    y = y_top - header_h - 8

    if not items:
        items = [{"prescription": "-", "indication": "-"}]

    for idx, item in enumerate(items):
        row_h = _rx_table_row_height(item)

        c.setFillColor(COLOR_WHITE if idx % 2 == 0 else COLOR_BG)
        c.setStrokeColor(COLOR_BORDER)
        c.roundRect(LEFT, y - row_h, CONTENT_WIDTH, row_h, 10, stroke=1, fill=1)
        c.line(mid_x, y - row_h, mid_x, y)

        left_text_top = y - 14
        right_text_top = y - 14

        _draw_paragraph(
            c,
            LEFT + 12,
            left_text_top,
            item.get("prescription") or "-",
            (CONTENT_WIDTH / 2) - 22,
            "Helvetica",
            10,
            COLOR_TEXT,
            3,
        )
        _draw_paragraph(
            c,
            mid_x + 10,
            right_text_top,
            item.get("indication") or "-",
            (CONTENT_WIDTH / 2) - 22,
            "Helvetica",
            10,
            COLOR_TEXT,
            3,
        )

        y -= row_h + 8

    return y


@router.get("/encounters/{encounter_id}/pdf")
def download_encounter_pdf(
    encounter_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    current_doctor = _require_login(request, db)
    if not current_doctor:
        return _redirect_login()

    enc = db.query(Encounter).filter(Encounter.id == encounter_id).first()
    if not enc:
        raise HTTPException(status_code=404, detail="Consulta no encontrada")

    patient = db.query(Patient).filter(Patient.id == enc.patient_id).first()
    note = db.query(ClinicalNote).filter(ClinicalNote.encounter_id == enc.id).first()
    attending_doctor = db.query(Doctor).filter(Doctor.id == enc.doctor_id).first()

    doc_name, doc_spec, doc_reg = _doctor_meta(attending_doctor)
    qr_text = _build_validation_url(request, enc)

    buf = BytesIO()
    c = canvas.Canvas(buf, pagesize=PAGE_SIZE)
    page_num = 1

    _draw_watermark(c)
    y = _draw_page_header(
        c,
        "Resumen Clínico",
        f"Atención #{enc.id}",
    )
    _draw_page_footer(c, page_num)
    page_num += 1

    chip_w = (CONTENT_WIDTH - 16) / 3
    _draw_info_chip(c, LEFT, y, "Documento", datetime.now().strftime("%Y-%m-%d %H:%M"), chip_w)
    _draw_info_chip(c, LEFT + chip_w + 8, y, "Fecha atención", _fmt_dt(_best_datetime(enc)), chip_w)
    _draw_info_chip(c, LEFT + (chip_w + 8) * 2, y, "Estado", "Cerrada" if enc.ended_at else "Abierta", chip_w)
    y -= 34

    meta_rows = [
        ("Centro", BRAND_NAME),
        ("Paciente", getattr(patient, "full_name", None) or "N/A"),
        ("Médico tratante", doc_name),
        ("Registro", doc_reg),
        ("Especialidad", doc_spec),
        ("Tipo de consulta", getattr(enc, "visit_type", None) or "-"),
        ("Motivo corto", getattr(enc, "chief_complaint_short", None) or "-"),
        ("ID atención", str(enc.id)),
    ]
    y = _draw_meta_grid(c, y, meta_rows, cols=2)

    blocks = [
        ("Motivo de consulta", note.chief_complaint if note else "-"),
        ("Enfermedad actual", note.hpi if note else "-"),
        ("__VITALS__", ""),
        ("Examen físico", note.physical_exam if note else "-"),
        ("Exámenes complementarios", note.complementary_tests if note else "-"),
        ("Impresión diagnóstica", note.assessment_dx if note else "-"),
        ("Prescripción / Plan", note.plan_treatment if note else "-"),
        ("Indicaciones y signos de alarma", note.indications_alarm_signs if note else "-"),
        ("Seguimiento", note.follow_up if note else "-"),
    ]

    for title, text in blocks:
        if title == "__VITALS__":
            needed = 90
            y, page_num = _ensure_space(c, y, needed, page_num, "Resumen Clínico", f"Atención #{enc.id}")
            y = _draw_vitals_card(c, y, note)
        else:
            needed = _section_height(title, text) + 6
            y, page_num = _ensure_space(c, y, needed, page_num, "Resumen Clínico", f"Atención #{enc.id}")
            y = _draw_section_card(c, y, title, text)

    y, page_num = _ensure_space(c, y, 150, page_num, "Resumen Clínico", f"Atención #{enc.id}")
    y = _draw_signature_block(c, y, attending_doctor, qr_text)

    c.save()
    buf.seek(0)

    filename = f"nexacenter_encounter_{encounter_id}.pdf"
    return StreamingResponse(
        buf,
        media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="{filename}"'},
    )


@router.get("/encounters/{encounter_id}/prescription/pdf")
def download_encounter_prescription_pdf(
    encounter_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    current_doctor = _require_login(request, db)
    if not current_doctor:
        return _redirect_login()

    enc = db.query(Encounter).filter(Encounter.id == encounter_id).first()
    if not enc:
        raise HTTPException(status_code=404, detail="Consulta no encontrada")

    patient = db.query(Patient).filter(Patient.id == enc.patient_id).first()
    attending_doctor = db.query(Doctor).filter(Doctor.id == enc.doctor_id).first()
    prescription_items = _load_prescription_items(enc)
    qr_text = _build_validation_url(request, enc)

    buf = BytesIO()
    c = canvas.Canvas(buf, pagesize=PAGE_SIZE)
    page_num = 1

    _draw_watermark(c)
    y = _draw_prescription_header(c, enc, patient, attending_doctor)
    _draw_page_footer(c, page_num)
    page_num += 1

    needed = 40
    y, page_num = _ensure_space(c, y, needed, page_num, "Receta Médica", f"Atención #{enc.id}")
    c.setFont("Helvetica-Bold", 12)
    c.setFillColor(COLOR_PRIMARY)
    c.drawString(LEFT, y, "Detalle de receta")
    y -= 16

    total_table_height = 36
    for item in prescription_items if prescription_items else [{"prescription": "-", "indication": "-"}]:
        total_table_height += _rx_table_row_height(item) + 8

    y, page_num = _ensure_space(c, y, total_table_height + 20, page_num, "Receta Médica", f"Atención #{enc.id}")
    y = _draw_prescription_table(c, y, prescription_items)

    y, page_num = _ensure_space(c, y, 150, page_num, "Receta Médica", f"Atención #{enc.id}")
    y = _draw_signature_block(c, y, attending_doctor, qr_text)

    c.save()
    buf.seek(0)

    filename = f"nexacenter_receta_{encounter_id}.pdf"
    return StreamingResponse(
        buf,
        media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="{filename}"'},
    )


@router.get("/patients/{patient_id}/history/pdf")
def download_patient_history_pdf(
    patient_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    current_doctor = _require_login(request, db)
    if not current_doctor:
        return _redirect_login()

    patient = db.query(Patient).filter(Patient.id == patient_id).first()
    if not patient:
        raise HTTPException(status_code=404, detail="Paciente no encontrado")

    encounters = db.query(Encounter).filter(Encounter.patient_id == patient_id).all()

    def sort_key(enc: Encounter):
        dt = _best_datetime(enc)
        return (dt is not None, dt, enc.id)

    encounters_sorted = sorted(encounters, key=sort_key, reverse=False)

    buf = BytesIO()
    c = canvas.Canvas(buf, pagesize=PAGE_SIZE)
    page_num = 1

    _draw_watermark(c)
    y = _draw_page_header(
        c,
        "Historia Clínica",
        f"Paciente #{patient_id}",
    )
    _draw_page_footer(c, page_num)
    page_num += 1

    chip_w = (CONTENT_WIDTH - 8) / 2
    _draw_info_chip(c, LEFT, y, "Paciente", getattr(patient, "full_name", None) or "N/A", chip_w)
    _draw_info_chip(c, LEFT + chip_w + 8, y, "Generado", datetime.now().strftime("%Y-%m-%d %H:%M"), chip_w)
    y -= 34

    if not encounters_sorted:
        y = _draw_section_card(c, y, "Historia clínica", "No existen atenciones registradas para este paciente.")
        c.save()
        buf.seek(0)
        filename = f"nexacenter_historia_paciente_{patient_id}.pdf"
        return StreamingResponse(
            buf,
            media_type="application/pdf",
            headers={"Content-Disposition": f'inline; filename="{filename}"'},
        )

    intro_rows = [
        ("Total atenciones", str(len(encounters_sorted))),
        ("Documento", "Consolidado clínico"),
        ("Centro", BRAND_NAME),
        ("Paciente ID", str(patient_id)),
    ]
    y = _draw_meta_grid(c, y, intro_rows, cols=2)

    for idx, enc in enumerate(encounters_sorted, start=1):
        note = db.query(ClinicalNote).filter(ClinicalNote.encounter_id == enc.id).first()
        attending_doctor = db.query(Doctor).filter(Doctor.id == enc.doctor_id).first()
        evols = (
            db.query(EncounterEvolution)
            .filter(EncounterEvolution.encounter_id == enc.id)
            .order_by(EncounterEvolution.created_at.asc())
            .all()
        )

        doc_name, doc_spec, doc_reg = _doctor_meta(attending_doctor)
        qr_text = _build_validation_url(request, enc)

        encounter_header_need = 150
        y, page_num = _ensure_space(c, y, encounter_header_need, page_num, "Historia Clínica", f"Paciente #{patient_id}")

        meta_rows = [
            ("Atención", f"#{enc.id}"),
            ("Fecha", _fmt_dt(_best_datetime(enc))),
            ("Médico", doc_name),
            ("Registro", doc_reg),
            ("Especialidad", doc_spec),
            ("Tipo consulta", getattr(enc, "visit_type", None) or "-"),
            ("Motivo corto", getattr(enc, "chief_complaint_short", None) or "-"),
            ("Estado", "Cerrada" if enc.ended_at else "Abierta"),
        ]
        y = _draw_meta_grid(c, y, meta_rows, cols=2)

        blocks = [
            ("Motivo de consulta", note.chief_complaint if note else "-"),
            ("Enfermedad actual", note.hpi if note else "-"),
            ("__VITALS__", ""),
            ("Examen físico", note.physical_exam if note else "-"),
            ("Exámenes complementarios", note.complementary_tests if note else "-"),
            ("Impresión diagnóstica", note.assessment_dx if note else "-"),
            ("Prescripción / Plan", note.plan_treatment if note else "-"),
            ("Indicaciones y signos de alarma", note.indications_alarm_signs if note else "-"),
            ("Seguimiento", note.follow_up if note else "-"),
        ]

        for title, text in blocks:
            if title == "__VITALS__":
                needed = 90
                y, page_num = _ensure_space(c, y, needed, page_num, "Historia Clínica", f"Paciente #{patient_id}")
                y = _draw_vitals_card(c, y, note)
            else:
                needed = _section_height(title, text) + 6
                y, page_num = _ensure_space(c, y, needed, page_num, "Historia Clínica", f"Paciente #{patient_id}")
                y = _draw_section_card(c, y, title, text)

        if evols:
            evo_text = "\n".join(
                f"{_fmt_dt(ev.created_at)} - Dr. ID {ev.author_doctor_id}: {ev.content}"
                for ev in evols
            )
        else:
            evo_text = "-"

        needed = _section_height("Evoluciones / Addendum", evo_text) + 6
        y, page_num = _ensure_space(c, y, needed, page_num, "Historia Clínica", f"Paciente #{patient_id}")
        y = _draw_section_card(c, y, "Evoluciones / Addendum", evo_text)

        y, page_num = _ensure_space(c, y, 150, page_num, "Historia Clínica", f"Paciente #{patient_id}")
        y = _draw_signature_block(c, y, attending_doctor, qr_text)
        y -= 6

    c.save()
    buf.seek(0)

    filename = f"nexacenter_historia_paciente_{patient_id}.pdf"
    return StreamingResponse(
        buf,
        media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="{filename}"'},
    )