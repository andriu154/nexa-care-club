from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from io import BytesIO
from datetime import datetime
import os
import textwrap

from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas
from reportlab.lib.colors import HexColor, white, black
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase.pdfmetrics import stringWidth

from ..database import get_db
from ..deps.auth import get_current_doctor
from ..models import Doctor, Patient, Encounter, ClinicalNote

router = APIRouter(prefix="/encounters", tags=["PDF"])

# =========================
# 🎨 Branding (CAMBIA HEX AQUÍ)
# =========================
BRAND_NAME = "NexaCenter"

# 👇 Reemplaza estos HEX por los colores oficiales de Nexa (si ya los tienes)
BRAND_PRIMARY = HexColor("#1F6FEB")   # Azul principal (ejemplo)
BRAND_ACCENT = HexColor("#00B3A4")    # Verde/teal acento (ejemplo)
BRAND_BG_LIGHT = HexColor("#F6F7FB")  # Fondo suave
BRAND_TEXT_MUTED = HexColor("#4B5563")  # Gris texto

# Logo (ruta absoluta para que sirva en Render)
LOGO_FILENAME = "logo.png"


def _asset_path(*parts: str) -> str:
    """
    Devuelve ruta absoluta dentro de app/assets.
    """
    base_dir = os.path.dirname(os.path.dirname(__file__))  # .../app
    return os.path.join(base_dir, "assets", *parts)


def _wrap_text(c: canvas.Canvas, text: str, max_width: float, font_name: str, font_size: int):
    """
    Envuelve texto según ancho real (stringWidth).
    Devuelve lista de líneas.
    """
    if not text:
        return ["-"]
    text = text.strip()
    if not text:
        return ["-"]

    words = text.replace("\r\n", "\n").split()
    lines = []
    current = ""

    for w in words:
        tentative = (current + " " + w).strip()
        if stringWidth(tentative, font_name, font_size) <= max_width:
            current = tentative
        else:
            if current:
                lines.append(current)
            current = w

    if current:
        lines.append(current)

    # Respeta saltos de línea originales (si el usuario escribió con \n)
    # Si hay \n, hacemos wrap por párrafos:
    if "\n" in text:
        lines = []
        for paragraph in text.replace("\r\n", "\n").split("\n"):
            paragraph = paragraph.strip()
            if not paragraph:
                lines.append("")
                continue
            words = paragraph.split()
            cur = ""
            for w in words:
                tent = (cur + " " + w).strip()
                if stringWidth(tent, font_name, font_size) <= max_width:
                    cur = tent
                else:
                    if cur:
                        lines.append(cur)
                    cur = w
            if cur:
                lines.append(cur)

    return lines


def _draw_header(c: canvas.Canvas, width: float, height: float, doctor_name: str):
    """
    Dibuja encabezado con barra de color + logo + título.
    """
    # Barra superior
    c.setFillColor(BRAND_PRIMARY)
    c.rect(0, height - 70, width, 70, stroke=0, fill=1)

    # Logo (si existe)
    logo_path = _asset_path(LOGO_FILENAME)
    if os.path.exists(logo_path):
        try:
            img = ImageReader(logo_path)
            # Ajuste de tamaño del logo
            c.drawImage(img, 35, height - 60, width=90, height=45, mask="auto")
        except Exception:
            # Si falla el logo, no rompemos el PDF
            pass

    # Título
    c.setFillColor(white)
    c.setFont("Helvetica-Bold", 16)
    c.drawString(140, height - 45, f"{BRAND_NAME} — Resumen de Consulta")

    # Subtítulo
    c.setFont("Helvetica", 9)
    c.drawString(140, height - 60, f"Documento clínico | Generado por: {doctor_name}")


def _draw_footer(c: canvas.Canvas, width: float, page_num: int):
    """
    Footer con confidencialidad + número de página.
    """
    c.setFillColor(BRAND_TEXT_MUTED)
    c.setFont("Helvetica", 8)
    c.drawString(35, 30, "Confidencial — Uso exclusivo para fines clínicos.")
    c.drawRightString(width - 35, 30, f"Página {page_num}")


@router.get("/{encounter_id}/pdf")
def download_encounter_pdf(
    encounter_id: int,
    db: Session = Depends(get_db),
    current_doctor: Doctor = Depends(get_current_doctor),
):
    # 1) traer consulta
    enc = db.query(Encounter).filter(Encounter.id == encounter_id).first()
    if not enc:
        raise HTTPException(status_code=404, detail="Consulta no encontrada")

    # 🔒 Solo el médico dueño puede descargar
    if enc.doctor_id != current_doctor.id:
        raise HTTPException(status_code=403, detail="No autorizado")

    # 2) traer paciente + nota
    patient = db.query(Patient).filter(Patient.id == enc.patient_id).first()
    note = db.query(ClinicalNote).filter(ClinicalNote.encounter_id == encounter_id).first()

    # 3) generar PDF en memoria
    buf = BytesIO()
    c = canvas.Canvas(buf, pagesize=letter)
    width, height = letter

    # layout
    LEFT = 35
    RIGHT = 35
    TOP_START = height - 85  # debajo del header
    CONTENT_WIDTH = width - LEFT - RIGHT

    page_num = 1

    def new_page():
        nonlocal page_num
        if page_num > 1:
            c.showPage()
        _draw_header(c, width, height, current_doctor.name)
        _draw_footer(c, width, page_num)
        page_num += 1

    def card_title(y, title: str):
        # Barra/etiqueta
        c.setFillColor(BRAND_BG_LIGHT)
        c.roundRect(LEFT, y - 18, CONTENT_WIDTH, 22, 6, stroke=0, fill=1)
        c.setFillColor(BRAND_PRIMARY)
        c.setFont("Helvetica-Bold", 11)
        c.drawString(LEFT + 10, y - 4, title)
        return y - 26

    def write_kv(y, items):
        """
        items: list of tuples (label, value)
        """
        c.setFont("Helvetica", 9)
        for label, value in items:
            if y < 80:
                new_page()
                y = TOP_START

            c.setFillColor(BRAND_TEXT_MUTED)
            c.drawString(LEFT + 10, y, f"{label}:")
            c.setFillColor(black)
            c.drawString(LEFT + 110, y, f"{value}")
            y -= 14
        return y

    def section(y, title: str, text: str | None):
        nonlocal page_num
        if y < 110:
            new_page()
            y = TOP_START

        y = card_title(y, title)

        c.setFont("Helvetica", 10)
        max_w = CONTENT_WIDTH - 20
        lines = _wrap_text(c, text if text else "-", max_w, "Helvetica", 10)

        c.setFillColor(black)
        for line in lines:
            if y < 70:
                new_page()
                y = TOP_START
                y = card_title(y, title + " (cont.)")
                c.setFont("Helvetica", 10)
            c.drawString(LEFT + 10, y, line)
            y -= 12

        y -= 6
        return y

    # ---- Página 1
    new_page()
    y = TOP_START

    # Encabezado de datos (card)
    y = card_title(y, "Datos generales")

    gen_date = datetime.now().strftime("%Y-%m-%d %H:%M")
    patient_name = patient.full_name if patient else "N/A"

    # Si tu Encounter tiene una fecha propia, úsala aquí.
    # Ejemplo: enc.created_at / enc.date / enc.start_time, depende de tu modelo.
    encounter_date = getattr(enc, "created_at", None)
    if encounter_date:
        try:
            encounter_date_str = encounter_date.strftime("%Y-%m-%d %H:%M")
        except Exception:
            encounter_date_str = str(encounter_date)
    else:
        encounter_date_str = "-"

    y = write_kv(y, [
        ("Centro", BRAND_NAME),
        ("Fecha del documento", gen_date),
        ("Fecha de la consulta", encounter_date_str),
        ("Médico", f"{current_doctor.name} (ID {current_doctor.id})"),
        ("Paciente", f"{patient_name} (ID {enc.patient_id})"),
        ("Tipo", f"{enc.visit_type}"),
        ("Motivo corto", f"{enc.chief_complaint_short or '-'}"),
    ])

    y -= 6

    # ---- Contenido clínico
    if note:
        y = section(y, "Motivo de consulta", note.chief_complaint)
        y = section(y, "Enfermedad actual", note.hpi)

        sv_parts = []
        if note.ta_sys is not None and note.ta_dia is not None:
            sv_parts.append(f"TA: {note.ta_sys}/{note.ta_dia}")
        if note.hr is not None:
            sv_parts.append(f"FC: {note.hr}")
        if note.rr is not None:
            sv_parts.append(f"FR: {note.rr}")
        if note.temp is not None:
            sv_parts.append(f"T°: {note.temp}")
        if note.spo2 is not None:
            sv_parts.append(f"SpO2: {note.spo2}%")

        y = section(y, "Signos vitales", " | ".join(sv_parts) if sv_parts else None)

        y = section(y, "Examen físico", note.physical_exam)
        y = section(y, "Exámenes complementarios", note.complementary_tests)
        y = section(y, "Impresión diagnóstica", note.assessment_dx)
        y = section(y, "Tratamiento / Plan", note.plan_treatment)
        y = section(y, "Signos de alarma", note.indications_alarm_signs)
        y = section(y, "Seguimiento", note.follow_up)
    else:
        y = section(y, "Nota clínica", "No hay nota clínica registrada para esta consulta.")

    c.save()
    buf.seek(0)

    filename = f"{BRAND_NAME.lower()}_consulta_{encounter_id}.pdf"
    return StreamingResponse(
        buf,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
