from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from ..database import get_db
from ..deps.auth import get_current_doctor
from ..models import Doctor, Patient, Encounter, ClinicalNote

router = APIRouter(prefix="/patients", tags=["History"])


def _best_datetime(enc: Encounter):
    for attr in ("ended_at", "encounter_date", "date", "start_time", "created_at", "updated_at"):
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
    patient = db.query(Patient).filter(Patient.id == patient_id).first()
    if not patient:
        raise HTTPException(status_code=404, detail="Paciente no encontrado")

    encounters = db.query(Encounter).filter(Encounter.patient_id == patient_id).all()

    def sort_key(enc: Encounter):
        dt = _best_datetime(enc)
        return (dt is not None, dt, enc.id)

    encounters_sorted = sorted(encounters, key=sort_key, reverse=True)

    base_url = str(request.base_url).rstrip("/")
    items = []

    for enc in encounters_sorted:
        attending = db.query(Doctor).filter(Doctor.id == enc.doctor_id).first()
        note = db.query(ClinicalNote).filter(ClinicalNote.encounter_id == enc.id).first()
        dt = _best_datetime(enc)

        items.append({
            "encounter_id": enc.id,
            "encounter_datetime": dt.isoformat() if dt else None,
            "visit_type": getattr(enc, "visit_type", None),
            "chief_complaint_short": getattr(enc, "chief_complaint_short", None),
            "attending_doctor": {
                "id": enc.doctor_id,
                "name": getattr(attending, "name", None) if attending else None,
                "specialty": getattr(attending, "specialty", None) if attending else None,
                "registration": getattr(attending, "registration", None) if attending else None,
            },
            "has_note": note is not None,
            "pdf_url": f"{base_url}/encounters/{enc.id}/pdf",
        })

    return {
        "patient": {"id": patient.id, "full_name": getattr(patient, "full_name", None)},
        "count": len(items),
        "items": items,
        "consolidated_pdf_url": f"{base_url}/patients/{patient_id}/history/pdf",
    }
