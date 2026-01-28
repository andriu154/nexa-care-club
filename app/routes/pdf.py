from fastapi import APIRouter, Depends, HTTPException
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

router = APIRouter(prefix="/encounters", tags=["PDF"])

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


def asset_path(filename: str) -> str:
    base = os.path.dirname(os.path.dirname(__file__))  # app/
    return os.path.join(base, "assets", filename)


def wrap_text(c, text, max_width, font, size):
    if not text:
        return ["-"]
    text = text.strip()
    if not text:
        return ["-"]

    # Respeta saltos de línea
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


def draw_watermark(c, width, height):
    """
    Marca de agua suave y premium. No usa alpha para no depender de versiones.
    Se logra con color muy claro + fuente grande + rotación.
    """
    c.saveState()
    c.setFillColor(COLOR_WATERMARK)
    c.setFont("Helvetica-Bold", 70)
    c.translate(width / 2, height / 2)
    c.rotate(25)
    c.drawCentredString(0, 0, BRAND_NAME.upper())
    c.restoreState()


def draw_header(c, width, height):
    """
    Header limpio: logo + título derecho.
    """
    y = height - 40
    logo_path = asset_path(LOGO_FILENAME)
    if os.path.exists(logo_path):
        try:
            c.drawImage(ImageReader(logo_path), 40, y - 40, width=120, height=40, mask="auto")
        except Exception:
            pass

    c.setFont("Helvetica-Bold", 18)
    c.setFillColor(COLOR_TITLE)
    c.drawRightString(width - 40, y - 15, "Resumen Clínico")
    return y - 70


def draw_footer(c, width):
    c.setFont("Helvetica", 8)
    c.setFillColor(COLOR_MUTED)
    c.drawString(40, 25, "Confidencial — Uso exclusivo para fines clínicos.")


@router.get("/{encounter_id}/pdf")
def download_encounter_pdf(
    encounter_id: int,
    db: Session = Depends(get_db),
    current_doctor: Doctor = Depends(get_current_doctor),
):
    # 1) Traer consulta
    enc = db.query(Encounter).filter(Encounter.id == encounter_id).first()
    if not enc:
        raise HTTPException(status_code=404, detail="Consulta no encontrada")

    # 🔒 Solo el médico dueño puede descargar
    if enc.doctor_id != current_doctor.id:
        raise HTTPException(status_code=403, detail="No autorizado")

    # 2) Paciente + nota
    patient = db.query(Patient).filter(Patient.id == enc.patient_id).first()
    note = db.query(ClinicalNote).filter(ClinicalNote.encounter_id == encounter_id).first()

    # 3) PDF en memoria
    buf = BytesIO()
    c = canvas.Canvas(buf, pagesize=letter)
    width, height = letter

    LEFT, RIGHT = 40, 40
    content_width = width - LEFT - RIGHT
    y = height - 40

    def new_page():
        nonlocal y
        c.showPage()
        draw_watermark(c, width, height)
        y = draw_header(c, width, height)
        draw_footer(c, width)

    # Primera página
    draw_watermark(c, width, height)
    y = draw_header(c, width, height)
    draw_footer(c, width)

    # -------- DATOS GENERALES --------
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
            new_page()
        c.setFont("Helvetica", 10)
        c.setFillColor(COLOR_MUTED)
        c.drawString(LEFT, y, f"{label}:")
        c.setFillColor(COLOR_TEXT)
        c.drawString(LEFT + 140, y, str(value))
        y -= 14

    row("Centro", BRAND_NAME)
    row("Fecha del documento", datetime.now().strftime("%Y-%m-%d %H:%M"))
    row("Médico tratante", current_doctor.name)
    row("Paciente", patient.full_name if patient else "N/A")
    row("Tipo de consulta", enc.visit_type)
    row("Motivo corto", enc.chief_complaint_short or "-")

    y -= 10

    # -------- SECCIONES CLÍNICAS --------
    def section(title, text):
        nonlocal y
        if y < 140:
            new_page()

        c.setFont("Helvetica-Bold", 11)
        c.setFillColor(COLOR_TITLE)
        c.drawString(LEFT, y, title)
        y -= 10
        c.setStrokeColor(COLOR_MUTED)
        c.line(LEFT, y, width - RIGHT, y)
        y -= 14

        c.setFont("Helvetica", 10)
        c.setFillColor(COLOR_TEXT)
        lines = wrap_text(c, text or "-", content_width, "Helvetica", 10)

        for line in lines:
            if y < 80:
                new_page()
                # Repite título en continuidad, elegante
                c.setFont("Helvetica-Bold", 11)
                c.setFillColor(COLOR_TITLE)
                c.drawString(LEFT, y, f"{title} (cont.)")
                y -= 10
                c.setStrokeColor(COLOR_MUTED)
                c.line(LEFT, y, width - RIGHT, y)
                y -= 14
                c.setFont("Helvetica", 10)
                c.setFillColor(COLOR_TEXT)

            # línea vacía para separar párrafos
            if line == "":
                y -= 6
            else:
                c.drawString(LEFT, y, line)
                y -= 12

        y -= 6

    if note:
        section("Motivo de consulta", note.chief_complaint)
        section("Enfermedad actual", note.hpi)

        # Signos vitales (si existen)
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

        section("Signos vitales", " | ".join(sv_parts) if sv_parts else "-")

        # Desglose claro de lo que escribe el médico
        section("Examen físico", note.physical_exam)
        section("Exámenes complementarios", note.complementary_tests)
        section("Impresión diagnóstica", note.assessment_dx)
        section("Prescripción / Plan", note.plan_treatment)
        section("Indicaciones y signos de alarma", note.indications_alarm_signs)
        section("Seguimiento", note.follow_up)
    else:
        section("Nota clínica", "No existe nota clínica registrada para esta consulta.")

    # -------- FIRMA + SELLO + REGISTRO --------
    if y < 190:
        new_page()

    y -= 10
    c.setFont("Helvetica-Bold", 11)
    c.setFillColor(COLOR_TITLE)
    c.drawString(LEFT, y, "Validación profesional")
    y -= 10
    c.setStrokeColor(COLOR_MUTED)
    c.line(LEFT, y, width - RIGHT, y)
    y -= 20

    # Caja premium para sello + registro
    box_height = 90
    c.setStrokeColor(COLOR_MUTED)
    c.setFillColor(COLOR_BG)
    c.roundRect(LEFT, y - box_height, content_width, box_height, 10, stroke=1, fill=1)

    c.setFillColor(COLOR_MUTED)
    c.setFont("Helvetica", 9)
    c.drawString(LEFT + 14, y - 18, "Firma del profesional:")
    c.drawString(LEFT + 14, y - 40, "Nombre:")
    c.drawString(LEFT + 14, y - 58, "Registro profesional:")

    # Líneas para firma + datos
    c.setStrokeColor(COLOR_MUTED)
    c.line(LEFT + 140, y - 22, LEFT + 320, y - 22)   # firma
    c.line(LEFT + 140, y - 44, LEFT + 320, y - 44)   # nombre
    c.line(LEFT + 140, y - 62, LEFT + 320, y - 62)   # registro

    # Autocompletar nombre médico
    c.setFillColor(COLOR_TEXT)
    c.setFont("Helvetica", 9)
    c.drawString(LEFT + 145, y - 40, current_doctor.name)

    # Sellado + registro impregnado en el mismo bloque (zona derecha)
    c.setFillColor(COLOR_MUTED)
    c.setFont("Helvetica", 9)
    c.drawString(LEFT + 360, y - 18, "Sello (incluye registro):")

    # Recuadro para sello
    c.setStrokeColor(COLOR_MUTED)
    c.setFillColor(HexColor("#FFFFFF"))
    c.roundRect(LEFT + 360, y - 78, 165, 55, 8, stroke=1, fill=1)

    # Nota discreta dentro del recuadro
    c.setFillColor(COLOR_MUTED)
    c.setFont("Helvetica-Oblique", 7)
    c.drawCentredString(LEFT + 360 + 82.5, y - 52, "Colocar sello aquí")

    c.save()
    buf.seek(0)

    filename = f"nexacenter_consulta_{encounter_id}.pdf"
    return StreamingResponse(
        buf,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
