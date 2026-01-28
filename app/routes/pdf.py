from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from io import BytesIO
from datetime import datetime
import os

from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas
from reportlab.lib.colors import HexColor
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase.pdfmetrics import stringWidth

from ..database import get_db
from ..deps.auth import get_current_doctor
from ..models import Doctor, Patient, Encounter, ClinicalNote

router = APIRouter(tags=["PDF"])

# =========================
# 🎨 NEXACENTER BRANDING (premium mono)
# =========================
BRAND_NAME = "NexaCenter"

COLOR_TEXT = HexColor("#111111")
COLOR_TITLE = HexColor("#2B2B2B")
COLOR_MUTED = HexColor("#6B6B6B")
COLOR_BG = HexColor("#F2F2F2")
COLOR_WATERMARK = HexColor("#E6E6E6")  # muy suave

LOGO_FILENAME = "logo.png"


def _asset_path(filename: str) -> str:
    base = os.path.dirname(os.path.dirname(__file__))  # app/
    return os.path.join(base, "assets", filename)


def _best_datetime(enc: Encounter):
    for attr in ("encounter_date", "date", "start_time", "created_at", "updated_at"):
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


def _wrap_text(c, text, max_width, font, size):
    if not text:
        return ["-"]
    text = text.strip()
    if not text:
        return ["-"]

    paragraphs = text.replace("\r\n", "\n").split("\n")
    lines = []
    for p in paragraphs:
        p = p.strip()
        if not p:
            lines.append("")
            continue

        words = p.split()
        current = ""
        for w in words:
            test = (current + " " + w).strip()
            if stringWidth(test, font, size) <= max_width:
                current = test
            else:
                if current:
                    lines.append(current)
                current = w
        if current:
            lines.append(current)
    return lines


def _draw_watermark(c, width, height):
    c.saveState()
    c.setFillColor(COLOR_WATERMARK)
    c.setFont("Helvetica-Bold", 70)
    c.translate(width / 2, height / 2)
    c.rotate(25)
    c.drawCentredString(0, 0, BRAND_NAME.upper())
    c.restoreState()


def _draw_header(c, width, height, title_right: str):
    LEFT = 40
    RIGHT = 40
    y = height - 40

    logo_path = _asset_path(LOGO_FILENAME)
    if os.path.exists(logo_path):
        try:
            img = ImageReader(logo_path)
            iw, ih = img.getSize()
            desired_w = 140
            scale = desired_w / float(iw)
            desired_h = ih * scale

            c.drawImage(
                img,
                LEFT,
                y - desired_h,
                width=desired_w,
                height=desired_h,
                mask="auto",
                preserveAspectRatio=True,
                anchor="nw",
            )
        except Exception:
            pass

    c.setFont("Helvetica-Bold", 18)
    c.setFillColor(COLOR_TITLE)
    c.drawRightString(width - RIGHT, y - 15, title_right)

    return y - 70


def _draw_footer(c, width, page_num: int):
    c.setFont("Helvetica", 8)
    c.setFillColor(COLOR_MUTED)
    c.drawString(40, 25, "Confidencial — Uso exclusivo para fines clínicos.")
    c.drawRightString(width - 40, 25, f"Pág. {page_num}")


def _doctor_registration_value(doctor: Doctor) -> str | None:
    for attr in ("license_number", "registration", "professional_registration", "cmp", "senescyt", "registry"):
        if hasattr(doctor, attr):
            val = getattr(doctor, attr)
            if val:
                return str(val)
    return None


def _section(c, width, height, LEFT, RIGHT, y, title, text):
    content_width = width - LEFT - RIGHT

    if y < 140:
        return None

    c.setFont("Helvetica-Bold", 11)
    c.setFillColor(COLOR_TITLE)
    c.drawString(LEFT, y, title)
    y -= 10

    c.setStrokeColor(COLOR_MUTED)
    c.line(LEFT, y, width - RIGHT, y)
    y -= 14

    c.setFont("Helvetica", 10)
    c.setFillColor(COLOR_TEXT)
    lines = _wrap_text(c, text or "-", content_width, "Helvetica", 10)

    for line in lines:
        if y < 80:
            return None
        if line == "":
            y -= 6
        else:
            c.drawString(LEFT, y, line)
            y -= 12

    y -= 6
    return y


def _signature_block(c, width, LEFT, RIGHT, y, attending_doctor: Doctor):
    content_width = width - LEFT - RIGHT

    c.setFont("Helvetica-Bold", 11)
    c.setFillColor(COLOR_TITLE)
    c.drawString(LEFT, y, "Validación profesional")
    y -= 10

    c.setStrokeColor(COLOR_MUTED)
    c.line(LEFT, y, width - RIGHT, y)
    y -= 20

    box_height = 90
    c.setStrokeColor(COLOR_MUTED)
    c.setFillColor(COLOR_BG)
    c.roundRect(LEFT, y - box_height, content_width, box_height, 10, stroke=1, fill=1)

    c.setFillColor(COLOR_MUTED)
    c.setFont("Helvetica", 9)
    c.drawString(LEFT + 14, y - 18, "Firma del profesional:")
    c.drawString(LEFT + 14, y - 40, "Nombre:")
    c.drawString(LEFT + 14, y - 58, "Registro profesional:")

    c.setStrokeColor(COLOR_MUTED)
    c.line(LEFT + 140, y - 22, LEFT + 320, y - 22)   # firma
    c.line(LEFT + 140, y - 44, LEFT + 320, y - 44)   # nombre
    c.line(LEFT + 140, y - 62, LEFT + 320, y - 62)   # registro

    c.setFillColor(COLOR_TEXT)
    c.setFont("Helvetica", 9)
    c.drawString(LEFT + 145, y - 40, getattr(attending_doctor, "name", "") or "-")

    reg_val = _doctor_registration_value(attending_doctor)
    if reg_val:
        c.drawString(LEFT + 145, y - 58, reg_val)

    c.setFillColor(COLOR_MUTED)
    c.setFont("Helvetica", 9)
    c.drawString(LEFT + 360, y - 18, "Sello (incluye registro):")

    c.setStrokeColor(COLOR_MUTED)
    c.setFillColor(HexColor("#FFFFFF"))
    c.roundRect(LEFT + 360, y - 78, 165, 55, 8, stroke=1, fill=1)

    c.setFillColor(COLOR_MUTED)
    c.setFont("Helvetica-Oblique", 7)
    c.drawCentredString(LEFT + 360 + 82.5, y - 52, "Colocar sello aquí")

    return y - box_height - 10


# =========================================================
# ✅ PDF INDIVIDUAL POR ATENCIÓN (encounter)
# Todos los médicos autenticados pueden descargar
# =========================================================
@router.get("/encounters/{encounter_id}/pdf")
def download_encounter_pdf(
    encounter_id: int,
    request: Request,
    db: Session = Depends(get_db),
    current_doctor: Doctor = Depends(get_current_doctor),
):
    enc = db.query(Encounter).filter(Encounter.id == encounter_id).first()
    if not enc:
        raise HTTPException(status_code=404, detail="Consulta no encontrada")

    # ✅ PERMISOS: ya NO restringimos por médico dueño
    # (la autoría se mantiene mostrando el doctor que atendió: enc.doctor_id)

    patient = db.query(Patient).filter(Patient.id == enc.patient_id).first()
    note = db.query(ClinicalNote).filter(ClinicalNote.encounter_id == encounter_id).first()
    attending_doctor = db.query(Doctor).filter(Doctor.id == enc.doctor_id).first()

    buf = BytesIO()
    c = canvas.Canvas(buf, pagesize=letter)
    width, height = letter

    LEFT, RIGHT = 40, 40
    page_num = 1

    def start_page(title_right: str):
        nonlocal y, page_num
        _draw_watermark(c, width, height)
        y = _draw_header(c, width, height, title_right=title_right)
        _draw_footer(c, width, page_num)
        page_num += 1

    def next_page(title_right: str):
        c.showPage()
        start_page(title_right)

    start_page("Resumen Clínico")

    # Datos generales
    c.setFont("Helvetica-Bold", 11)
    c.setFillColor(COLOR_TITLE)
    c.drawString(LEFT, y, "Datos generales")
    y -= 12
    c.setStrokeColor(COLOR_MUTED)
    c.line(LEFT, y, width - RIGHT, y)
    y -= 18

    def row(label, value):
        nonlocal y
        if y < 110:
            next_page("Resumen Clínico")
        c.setFont("Helvetica", 10)
        c.setFillColor(COLOR_MUTED)
        c.drawString(LEFT, y, f"{label}:")
        c.setFillColor(COLOR_TEXT)
        c.drawString(LEFT + 140, y, str(value))
        y -= 14

    row("Centro", BRAND_NAME)
    row("Fecha del documento", datetime.now().strftime("%Y-%m-%d %H:%M"))
    row("Fecha de la atención", _fmt_dt(_best_datetime(enc)))
    row("Médico tratante", getattr(attending_doctor, "name", None) or "-")
    row("Paciente", getattr(patient, "full_name", None) or "N/A")
    row("Tipo de consulta", getattr(enc, "visit_type", None) or "-")
    row("Motivo corto", getattr(enc, "chief_complaint_short", None) or "-")
    y -= 10

    def render_section(title, text):
        nonlocal y
        y2 = _section(c, width, height, LEFT, RIGHT, y, title, text)
        if y2 is None:
            next_page("Resumen Clínico")
            y2 = _section(c, width, height, LEFT, RIGHT, y, f"{title} (cont.)", text)
            while y2 is None:
                next_page("Resumen Clínico")
                y2 = _section(c, width, height, LEFT, RIGHT, y, f"{title} (cont.)", text)
        y = y2

    if note:
        render_section("Motivo de consulta", note.chief_complaint)
        render_section("Enfermedad actual", note.hpi)

        sv_parts = []
        if getattr(note, "ta_sys", None) is not None and getattr(note, "ta_dia", None) is not None:
            sv_parts.append(f"TA: {note.ta_sys}/{note.ta_dia}")
        if getattr(note, "hr", None) is not None:
            sv_parts.append(f"FC: {note.hr}")
        if getattr(note, "rr", None) is not None:
            sv_parts.append(f"FR: {note.rr}")
        if getattr(note, "temp", None) is not None:
            sv_parts.append(f"T°: {note.temp}")
        if getattr(note, "spo2", None) is not None:
            sv_parts.append(f"SpO2: {note.spo2}%")

        render_section("Signos vitales", " | ".join(sv_parts) if sv_parts else "-")
        render_section("Examen físico", note.physical_exam)
        render_section("Exámenes complementarios", note.complementary_tests)
        render_section("Impresión diagnóstica", note.assessment_dx)
        render_section("Prescripción / Plan", note.plan_treatment)
        render_section("Indicaciones y signos de alarma", note.indications_alarm_signs)
        render_section("Seguimiento", note.follow_up)
    else:
        render_section("Nota clínica", "No existe nota clínica registrada para esta atención.")

    if y < 190:
        next_page("Resumen Clínico")

    y = _signature_block(c, width, LEFT, RIGHT, y, attending_doctor or current_doctor)

    c.save()
    buf.seek(0)

    filename = f"nexacenter_encounter_{encounter_id}.pdf"
    return StreamingResponse(
        buf,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# =========================================================
# ✅ PDF CONSOLIDADO POR PACIENTE + ÍNDICE
# Todas las atenciones en 1 PDF, cada una con su médico + firma/sello
# =========================================================
@router.get("/patients/{patient_id}/history/pdf")
def download_patient_history_pdf(
    patient_id: int,
    request: Request,
    db: Session = Depends(get_db),
    current_doctor: Doctor = Depends(get_current_doctor),
):
    patient = db.query(Patient).filter(Patient.id == patient_id).first()
    if not patient:
        raise HTTPException(status_code=404, detail="Paciente no encontrado")

    encounters = db.query(Encounter).filter(Encounter.patient_id == patient_id).all()

    def sort_key(enc: Encounter):
        dt = _best_datetime(enc)
        has_dt = dt is not None
        return (has_dt, dt, enc.id)

    encounters_sorted = sorted(encounters, key=sort_key, reverse=False)

    buf = BytesIO()
    c = canvas.Canvas(buf, pagesize=letter)
    width, height = letter

    LEFT, RIGHT = 40, 40
    content_width = width - LEFT - RIGHT
    page_num = 1

    def start_page(title_right: str):
        nonlocal y, page_num
        _draw_watermark(c, width, height)
        y = _draw_header(c, width, height, title_right=title_right)
        _draw_footer(c, width, page_num)
        page_num += 1

    def next_page(title_right: str):
        c.showPage()
        start_page(title_right)

    start_page("Historia Clínica — Consolidado")

    # ===== Encabezado paciente =====
    c.setFont("Helvetica-Bold", 12)
    c.setFillColor(COLOR_TITLE)
    c.drawString(LEFT, y, "Paciente")
    y -= 10
    c.setStrokeColor(COLOR_MUTED)
    c.line(LEFT, y, width - RIGHT, y)
    y -= 18

    c.setFont("Helvetica", 10)
    c.setFillColor(COLOR_MUTED)
    c.drawString(LEFT, y, "Nombre:")
    c.setFillColor(COLOR_TEXT)
    c.drawString(LEFT + 140, y, getattr(patient, "full_name", None) or "N/A")
    y -= 14

    c.setFillColor(COLOR_MUTED)
    c.drawString(LEFT, y, "Generado:")
    c.setFillColor(COLOR_TEXT)
    c.drawString(LEFT + 140, y, datetime.now().strftime("%Y-%m-%d %H:%M"))
    y -= 22

    if not encounters_sorted:
        c.setFillColor(COLOR_TEXT)
        c.setFont("Helvetica", 10)
        c.drawString(LEFT, y, "No existen atenciones registradas para este paciente.")
        c.save()
        buf.seek(0)
        filename = f"nexacenter_historia_paciente_{patient_id}.pdf"
        return StreamingResponse(
            buf,
            media_type="application/pdf",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )

    # ===== ÍNDICE =====
    c.setFont("Helvetica-Bold", 12)
    c.setFillColor(COLOR_TITLE)
    c.drawString(LEFT, y, "Índice de atenciones")
    y -= 10
    c.setStrokeColor(COLOR_MUTED)
    c.line(LEFT, y, width - RIGHT, y)
    y -= 16

    c.setFont("Helvetica", 9)
    for idx, enc in enumerate(encounters_sorted, start=1):
        if y < 90:
            next_page("Historia Clínica — Consolidado")

        attending_doctor = db.query(Doctor).filter(Doctor.id == enc.doctor_id).first()
        line = (
            f"{idx}. "
            f"{_fmt_dt(_best_datetime(enc))}  |  "
            f"{(getattr(attending_doctor, 'name', None) or '—')}  |  "
            f"{(getattr(enc, 'visit_type', None) or '—')}  |  "
            f"{(getattr(enc, 'chief_complaint_short', None) or '—')}"
        )

        c.setFillColor(COLOR_TEXT)
        # wrap suave para índice
        lines = _wrap_text(c, line, content_width, "Helvetica", 9)
        for ln in lines:
            if y < 90:
                next_page("Historia Clínica — Consolidado")
            c.drawString(LEFT, y, ln)
            y -= 12
        y -= 4

    # Comenzar detalle en nueva página (más limpio)
    next_page("Historia Clínica — Consolidado")

    def render_section(title, text):
        nonlocal y
        y2 = _section(c, width, height, LEFT, RIGHT, y, title, text)
        if y2 is None:
            next_page("Historia Clínica — Consolidado")
            y2 = _section(c, width, height, LEFT, RIGHT, y, f"{title} (cont.)", text)
            while y2 is None:
                next_page("Historia Clínica — Consolidado")
                y2 = _section(c, width, height, LEFT, RIGHT, y, f"{title} (cont.)", text)
        y = y2

    # ===== Detalle de cada atención (cada una con su firma/sello) =====
    for idx, enc in enumerate(encounters_sorted, start=1):
        note = db.query(ClinicalNote).filter(ClinicalNote.encounter_id == enc.id).first()
        attending_doctor = db.query(Doctor).filter(Doctor.id == enc.doctor_id).first()

        # Forzar que cada atención empiece bien, y si no cabe, nueva página
        if y < 180:
            next_page("Historia Clínica — Consolidado")

        c.setFont("Helvetica-Bold", 12)
        c.setFillColor(COLOR_TITLE)
        c.drawString(LEFT, y, f"Atención {idx}")
        y -= 10
        c.setStrokeColor(COLOR_MUTED)
        c.line(LEFT, y, width - RIGHT, y)
        y -= 16

        c.setFont("Helvetica", 10)
        c.setFillColor(COLOR_MUTED)
        c.drawString(LEFT, y, "Fecha de la atención:")
        c.setFillColor(COLOR_TEXT)
        c.drawString(LEFT + 140, y, _fmt_dt(_best_datetime(enc)))
        y -= 14

        c.setFillColor(COLOR_MUTED)
        c.drawString(LEFT, y, "Médico tratante:")
        c.setFillColor(COLOR_TEXT)
        c.drawString(LEFT + 140, y, getattr(attending_doctor, "name", None) or "-")
        y -= 14

        c.setFillColor(COLOR_MUTED)
        c.drawString(LEFT, y, "Tipo:")
        c.setFillColor(COLOR_TEXT)
        c.drawString(LEFT + 140, y, getattr(enc, "visit_type", None) or "-")
        y -= 18

        if note:
            render_section("Motivo de consulta", note.chief_complaint)
            render_section("Enfermedad actual", note.hpi)

            sv_parts = []
            if getattr(note, "ta_sys", None) is not None and getattr(note, "ta_dia", None) is not None:
                sv_parts.append(f"TA: {note.ta_sys}/{note.ta_dia}")
            if getattr(note, "hr", None) is not None:
                sv_parts.append(f"FC: {note.hr}")
            if getattr(note, "rr", None) is not None:
                sv_parts.append(f"FR: {note.rr}")
            if getattr(note, "temp", None) is not None:
                sv_parts.append(f"T°: {note.temp}")
            if getattr(note, "spo2", None) is not None:
                sv_parts.append(f"SpO2: {note.spo2}%")

            render_section("Signos vitales", " | ".join(sv_parts) if sv_parts else "-")
            render_section("Examen físico", note.physical_exam)
            render_section("Exámenes complementarios", note.complementary_tests)
            render_section("Impresión diagnóstica", note.assessment_dx)
            render_section("Prescripción / Plan", note.plan_treatment)
            render_section("Indicaciones y signos de alarma", note.indications_alarm_signs)
            render_section("Seguimiento", note.follow_up)
        else:
            render_section("Nota clínica", "No existe nota clínica registrada para esta atención.")

        if y < 200:
            next_page("Historia Clínica — Consolidado")
        y = _signature_block(c, width, LEFT, RIGHT, y, attending_doctor or current_doctor)

        # Separación elegante
        y -= 10
        if y > 110:
            c.setStrokeColor(COLOR_BG)
            c.line(LEFT, y, width - RIGHT, y)
            y -= 12

    c.save()
    buf.seek(0)

    filename = f"nexacenter_historia_paciente_{patient_id}.pdf"
    return StreamingResponse(
        buf,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
