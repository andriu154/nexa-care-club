from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from ..database import get_db
from ..deps.auth import get_current_doctor
from ..models import Doctor, Patient, Encounter, ClinicalNote

router = APIRouter(prefix="/patients", tags=["History"])


def _best_datetime(enc: Encounter):
    """
    Intenta obtener una fecha/hora de la consulta de forma robusta.
    Ajusta este orden si tu modelo tiene un campo específico.
    """
    for attr in ("encounter_date", "date", "start_time", "created_at", "updated_at"):
        if hasattr(enc, attr):
            val = getattr(enc, attr)
            if val is not None:
                return val
    return None


@router.get("/{patient_id}/history")
def get_patient_history(
    patient_id: int,
    request: Request,
    db: Session = Depends(get_db),
    current_doctor: Doctor = Depends(get_current_doctor),
):
    # 1) Validar paciente
    patient = db.query(Patient).filter(Patient.id == patient_id).first()
    if not patient:
        raise HTTPException(status_code=404, detail="Paciente no encontrado")

    # 2) Traer TODOS los encounters del paciente (de todos los médicos)
    encounters = (
        db.query(Encounter)
        .filter(Encounter.patient_id == patient_id)
        .all()
    )

    # 3) Ordenar: por fecha si existe; fallback por id
    def sort_key(enc: Encounter):
        dt = _best_datetime(enc)
        has_dt = dt is not None
        return (has_dt, dt, enc.id)

    encounters_sorted = sorted(encounters, key=sort_key, reverse=True)

    # 4) Preparar respuesta (incluye doctor que atendió)
    base_url = str(request.base_url).rstrip("/")  # ej: https://nexa-care-club.onrender.com
    items = []

    for enc in encounters_sorted:
        # Doctor que atendió
        attending_doctor = db.query(Doctor).filter(Doctor.id == enc.doctor_id).first()
        attending_name = getattr(attending_doctor, "name", None) if attending_doctor else None

        # Nota clínica (si existe)
        note = (
            db.query(ClinicalNote)
            .filter(ClinicalNote.encounter_id == enc.id)
            .first()
        )

        # Resumen útil para timeline
        summary = None
        dx = None
        if note:
            summary = note.chief_complaint or note.hpi or None
            dx = note.assessment_dx or None

        enc_dt = _best_datetime(enc)
        enc_dt_str = None
        if enc_dt is not None:
            try:
                enc_dt_str = enc_dt.isoformat()
            except Exception:
                enc_dt_str = str(enc_dt)

        # ⚠️ PDF: tu endpoint /encounters/{id}/pdf todavía restringe al médico dueño.
        pdf_url = f"{base_url}/encounters/{enc.id}/pdf"
        pdf_access = (enc.doctor_id == current_doctor.id)

        items.append(
            {
                "encounter_id": enc.id,
                "encounter_datetime": enc_dt_str,
                "visit_type": getattr(enc, "visit_type", None),
                "chief_complaint_short": getattr(enc, "chief_complaint_short", None),

                "attending_doctor": {
                    "id": enc.doctor_id,
                    "name": attending_name,
                },

                "has_note": note is not None,
                "summary": summary,
                "diagnosis": dx,

                "pdf_url": pdf_url,
                "pdf_access": pdf_access,
            }
        )

    return {
        "patient": {
            "id": patient.id,
            "full_name": getattr(patient, "full_name", None),
        },
        "requested_by_doctor": {
            "id": current_doctor.id,
            "name": getattr(current_doctor, "name", None),
        },
        "count": len(items),
        "items": items,
    }
