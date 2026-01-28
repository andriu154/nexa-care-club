from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from io import BytesIO
from datetime import datetime
from typing import Optional

from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas

from ..database import get_db
from ..deps.auth import get_current_doctor
from ..models import Doctor, Patient, Encounter, ClinicalNote

router = APIRouter(prefix="/encounters", tags=["PDF"])


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

    y = height - 40

    # Título
    c.setFont("Helvetica-Bold", 14)
    c.drawString(40, y, "Nexa Care Club - Consulta Médica (MG)")
    y -= 18

    # Encabezado
    c.setFont("Helvetica", 10)
    c.drawString(40, y, f"Fecha generación: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    y -= 14
    c.drawString(40, y, f"Médico: {current_doctor.name} (ID {current_doctor.id})")
    y -= 14
    c.drawString(40, y, f"Paciente: {(patient.full_name if patient else 'N/A')} (ID {enc.patient_id})")
    y -= 18

    # Resumen visita
    c.setFont("Helvetica-Bold", 11)
    c.drawString(40, y, "Resumen de visita")
    y -= 14
    c.setFont("Helvetica", 10)
    c.drawString(40, y, f"Tipo: {enc.visit_type} | Motivo corto: {enc.chief_complaint_short or '-'}")
    y -= 18

    def section(title: str, text: Optional[str]):
        nonlocal y
        if y < 90:
            c.showPage()
            y = height - 40

        c.setFont("Helvetica-Bold", 11)
        c.drawString(40, y, title)
        y -= 14

        c.setFont("Helvetica", 10)
        content = text.strip() if text else "-"
        for line in content.split("\n"):
            if y < 70:
                c.showPage()
                y = height - 40
                c.setFont("Helvetica", 10)
            c.drawString(50, y, line[:120])
            y -= 12
        y -= 8

    if note:
        section("Motivo de consulta", note.chief_complaint)
        section("Enfermedad actual", note.hpi)

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

        section("Signos vitales", " | ".join(sv_parts) if sv_parts else None)

        section("Examen físico", note.physical_exam)
        section("Exámenes complementarios", note.complementary_tests)
        section("Impresión diagnóstica", note.assessment_dx)
        section("Tratamiento / Plan", note.plan_treatment)
        section("Signos de alarma", note.indications_alarm_signs)
        section("Seguimiento", note.follow_up)
    else:
        section("Nota clínica", "No hay nota clínica registrada para esta consulta.")

    c.setFont("Helvetica-Oblique", 9)
    c.drawString(40, 50, "Documento generado solo bajo solicitud del médico.")
    c.showPage()
    c.save()

    buf.seek(0)

    filename = f"consulta_encounter_{encounter_id}.pdf"
    return StreamingResponse(
        buf,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
