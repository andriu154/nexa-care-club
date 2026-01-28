from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from sqlalchemy import asc, desc
from io import BytesIO
from datetime import datetime

from reportlab.lib.pagesizes import letter
from reportlab.lib.units import inch
from reportlab.lib import colors
from reportlab.pdfgen import canvas

from ..database import get_db
from ..models import Patient, Encounter, Doctor, ClinicalNote, EncounterEvolution

router = APIRouter(prefix="/patients", tags=["History"])


# -------------------------
# Helpers PDF branding
# -------------------------
def _brand_header(c: canvas.Canvas, title: str, subtitle: str | None = None):
    width, height = letter

    # Header line
    c.setStrokeColor(colors.HexColor("#D0D0D0"))
    c.setLineWidth(0.8)
    c.line(40, height - 72, width - 40, height - 72)

    # Title
    c.setFont("Helvetica-Bold", 16)
    c.setFillColor(colors.HexColor("#111111"))
    c.drawString(40, height - 52, title)

    # Subtitle
    if subtitle:
        c.setFont("Helvetica", 10)
        c.setFillColor(colors.HexColor("#555555"))
        c.drawString(40, height - 66, subtitle)


def _watermark(c: canvas.Canvas, text: str = "NexaCenter"):
    width, height = letter
    c.saveState()
    try:
        c.setFillAlpha(0.06)
    except Exception:
        pass
    c.setFont("Helvetica-Bold", 72)
    c.setFillColor(colors.HexColor("#000000"))
    c.translate(width / 2, height / 2)
    c.rotate(30)
    c.drawCentredString(0, 0, text)
    c.restoreState()


def _wrap_text(text: str, max_chars: int = 105):
    text = (text or "").strip()
    if not text:
        return ["-"]
    lines = []
    for raw in text.split("\n"):
        raw = raw.rstrip()
        if not raw:
            lines.append("")
            continue
        while len(raw) > max_chars:
            lines.append(raw[:max_chars])
            raw = raw[max_chars:]
        lines.append(raw)
    return lines


def _section(c: canvas.Canvas, y: float, title: str, text: str | None):
    width, height = letter

    # new page if needed
    if y < 110:
        c.showPage()
        _watermark(c)
        y = height - 95

    c.setFont("Helvetica-Bold", 11)
    c.setFillColor(colors.HexColor("#111111"))
    c.drawString(40, y, title)
    y -= 14

    c.setFont("Helvetica", 10)
    c.setFillColor(colors.HexColor("#222222"))

    for line in _wrap_text(text):
        if y < 80:
            c.showPage()
            _watermark(c)
            y = height - 95
            c.setFont("Helvetica", 10)
            c.setFillColor(colors.HexColor("#222222"))
        c.drawString(50, y, line[:160])
        y -= 12

    y -= 8
    return y


def _signature_block(c: canvas.Canvas, y: float, doctor: Doctor | None, enc: Encounter):
    """
    Recuadro para firma y sello (cada atención).
    """
    width, height = letter
    if y < 160:
        c.showPage()
        _watermark(c)
        y = height - 120

    # box
    c.setStrokeColor(colors.HexColor("#222222"))
    c.setLineWidth(1)
    c.rect(40, y - 95, width - 80, 90, stroke=1, fill=0)

    # label
    c.setFont("Helvetica-Bold", 10)
    c.setFillColor(colors.HexColor("#111111"))
    c.drawString(50, y - 20, "Firma y sello del profesional")

    # signature line
    c.setStrokeColor(colors.HexColor("#666666"))
    c.setLineWidth(0.8)
    c.line(50, y - 55, 300, y - 55)
    c.setFont("Helvetica", 9)
    c.setFillColor(colors.HexColor("#555555"))
    c.drawString(50, y - 68, "Firma")

    # stamp area
    c.setStrokeColor(colors.HexColor("#666666"))
    c.rect(330, y - 80, width - 80 - 330 + 40, 55, stroke=1, fill=0)
    c.setFont("Helvetica", 9)
    c.setFillColor(colors.HexColor("#555555"))
    c.drawString(335, y - 68, "Sello / Registro")

    # doctor printed info
    dn = doctor.name if doctor else "N/A"
    spec = getattr(doctor, "specialty", None) if doctor else None
    reg = getattr(doctor, "registration", None) if doctor else None
    when = enc.ended_at or enc.created_at

    c.setFont("Helvetica", 9)
    c.setFillColor(colors.HexColor("#222222"))
    c.drawString(50, y - 35, f"Profesional: {dn}")
    if spec:
        c.drawString(50, y - 47, f"Especialidad: {spec}")
    if reg:
        c.drawString(50, y - 59, f"Registro: {reg}")
    if when:
        c.drawString(50, y - 71, f"Fecha: {when.strftime('%Y-%m-%d %H:%M')}")

    return y - 115


# -------------------------
# A) Timeline endpoint
# -------------------------
@router.get("/{patient_id}/timeline")
def get_patient_timeline(patient_id: int, db: Session = Depends(get_db)):
    patient = db.query(Patient).filter(Patient.id == patient_id).first()
    if not patient:
        raise HTTPException(status_code=404, detail="Paciente no encontrado")

    encounters = (
        db.query(Encounter)
        .filter(Encounter.patient_id == patient_id)
        .order_by(desc(Encounter.created_at), desc(Encounter.id))
        .all()
    )

    items = []
    for enc in encounters:
        doc = db.query(Doctor).filter(Doctor.id == enc.doctor_id).first()
        items.append(
            {
                "encounter_id": enc.id,
                "created_at": enc.created_at.isoformat() if enc.created_at else None,
                "ended_at": enc.ended_at.isoformat() if enc.ended_at else None,
                "visit_type": enc.visit_type,
                "chief_complaint_short": enc.chief_complaint_short,
                "doctor": {
                    "id": doc.id if doc else enc.doctor_id,
                    "name": doc.name if doc else None,
                    "specialty": getattr(doc, "specialty", None) if doc else None,
                    "registration": getattr(doc, "registration", None) if doc else None,
                },
                "pdf_url": f"/encounters/{enc.id}/pdf",
            }
        )

    return {
        "patient": {
            "id": patient.id,
            "full_name": patient.full_name,
            "qr_code": patient.qr_code,
            "status": patient.status,
            "total_sessions": patient.total_sessions,
            "completed_sessions": patient.completed_sessions,
        },
        "items": items,
        "consolidated_pdf_url": f"/patients/{patient.id}/history/pdf",
    }


# -------------------------
# PDF Consolidado con índice
# -------------------------
@router.get("/{patient_id}/history/pdf")
def download_patient_history_pdf(patient_id: int, db: Session = Depends(get_db)):
    patient = db.query(Patient).filter(Patient.id == patient_id).first()
    if not patient:
        raise HTTPException(status_code=404, detail="Paciente no encontrado")

    encounters = (
        db.query(Encounter)
        .filter(Encounter.patient_id == patient_id)
        .order_by(asc(Encounter.created_at), asc(Encounter.id))
        .all()
    )

    buf = BytesIO()
    c = canvas.Canvas(buf, pagesize=letter)
    width, height = letter

    # Cover / Index
    _watermark(c)
    _brand_header(
        c,
        "NexaCenter",
        f"Historial clínico consolidado — Paciente: {patient.full_name} (ID {patient.id})",
    )

    y = height - 105
    c.setFont("Helvetica", 10)
    c.setFillColor(colors.HexColor("#333333"))
    c.drawString(40, y, f"Generado: {datetime.utcnow().strftime('%Y-%m-%d %H:%M')} UTC")
    y -= 18

    c.setFont("Helvetica-Bold", 12)
    c.setFillColor(colors.HexColor("#111111"))
    c.drawString(40, y, "Índice de atenciones")
    y -= 16

    c.setFont("Helvetica", 10)
    c.setFillColor(colors.HexColor("#222222"))
    if not encounters:
        c.drawString(40, y, "No existen atenciones registradas.")
        c.showPage()
    else:
        for i, enc in enumerate(encounters, start=1):
            doc = db.query(Doctor).filter(Doctor.id == enc.doctor_id).first()
            when = enc.ended_at or enc.created_at
            when_str = when.strftime("%Y-%m-%d %H:%M") if when else "N/A"
            dname = doc.name if doc else f"Doctor ID {enc.doctor_id}"
            short = enc.chief_complaint_short or "-"
            line = f"{i}. {when_str} — {dname} — {short}"
            if y < 90:
                c.showPage()
                _watermark(c)
                _brand_header(c, "NexaCenter", f"Índice — {patient.full_name}")
                y = height - 105
                c.setFont("Helvetica", 10)
                c.setFillColor(colors.HexColor("#222222"))
            c.drawString(40, y, line[:140])
            y -= 12

        c.showPage()

    # Body: each encounter
    for idx, enc in enumerate(encounters, start=1):
        doc = db.query(Doctor).filter(Doctor.id == enc.doctor_id).first()
        note = db.query(ClinicalNote).filter(ClinicalNote.encounter_id == enc.id).first()
        evols = (
            db.query(EncounterEvolution)
            .filter(EncounterEvolution.encounter_id == enc.id)
            .order_by(asc(EncounterEvolution.created_at))
            .all()
        )

        _watermark(c)
        subtitle = f"Atención #{idx} — Encounter ID {enc.id}"
        _brand_header(c, "NexaCenter", subtitle)

        y = height - 105
        when = enc.ended_at or enc.created_at
        when_str = when.strftime("%Y-%m-%d %H:%M") if when else "N/A"

        c.setFont("Helvetica", 10)
        c.setFillColor(colors.HexColor("#222222"))
        c.drawString(40, y, f"Paciente: {patient.full_name} (ID {patient.id})")
        y -= 14
        c.drawString(40, y, f"Fecha: {when_str}")
        y -= 14

        if doc:
            c.drawString(40, y, f"Profesional: {doc.name}")
            y -= 14
            extra = []
            if getattr(doc, "specialty", None):
                extra.append(f"{doc.specialty}")
            if getattr(doc, "registration", None):
                extra.append(f"Reg. {doc.registration}")
            if extra:
                c.drawString(40, y, " — ".join(extra)[:150])
                y -= 14
        else:
            c.drawString(40, y, f"Profesional ID: {enc.doctor_id}")
            y -= 14

        c.setStrokeColor(colors.HexColor("#D0D0D0"))
        c.setLineWidth(0.8)
        c.line(40, y, width - 40, y)
        y -= 18

        # Main note sections
        if note:
            y = _section(c, y, "Motivo de consulta", note.chief_complaint)
            y = _section(c, y, "Enfermedad actual", note.hpi)

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
            y = _section(c, y, "Signos vitales", " | ".join(sv_parts) if sv_parts else None)

            y = _section(c, y, "Examen físico", note.physical_exam)
            y = _section(c, y, "Exámenes complementarios", note.complementary_tests)
            y = _section(c, y, "Impresión diagnóstica", note.assessment_dx)
            y = _section(c, y, "Prescripción / Tratamiento", note.plan_treatment)
            y = _section(c, y, "Signos de alarma", note.indications_alarm_signs)
            y = _section(c, y, "Seguimiento", note.follow_up)
        else:
            y = _section(c, y, "Nota clínica", "No hay nota clínica registrada para esta atención.")

        # Evolutions / addenda
        if evols:
            y = _section(c, y, "Evoluciones / Addendum", None)
            for ev in evols:
                author = db.query(Doctor).filter(Doctor.id == ev.author_doctor_id).first()
                who = author.name if author else f"Doctor ID {ev.author_doctor_id}"
                stamp = ev.created_at.strftime("%Y-%m-%d %H:%M") if ev.created_at else ""
                y = _section(c, y, f"- {stamp} — {who}", ev.content)

        # Signature & stamp block per encounter
        y = _signature_block(c, y, doc, enc)

        c.setFont("Helvetica-Oblique", 8.5)
        c.setFillColor(colors.HexColor("#555555"))
        c.drawString(40, 45, "Documento generado desde NexaCenter. Uso clínico interno.")
        c.showPage()

    c.save()
    buf.seek(0)

    filename = f"historial_paciente_{patient_id}.pdf"
    return StreamingResponse(
        buf,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
