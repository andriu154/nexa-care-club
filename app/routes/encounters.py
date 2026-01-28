from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from datetime import datetime

from ..database import get_db
from ..deps.auth import get_current_doctor
from ..models import Doctor, Patient, Encounter

router = APIRouter(prefix="/encounters", tags=["Encounters"])


@router.post("/")
def create_encounter(payload: dict, db: Session = Depends(get_db), current_doctor: Doctor = Depends(get_current_doctor)):
    patient_id = payload.get("patient_id")
    if not patient_id:
        raise HTTPException(status_code=400, detail="patient_id es requerido")

    patient = db.query(Patient).filter(Patient.id == int(patient_id)).first()
    if not patient:
        raise HTTPException(status_code=404, detail="Paciente no encontrado")

    enc = Encounter(
        patient_id=patient.id,
        doctor_id=current_doctor.id,
        visit_type=payload.get("visit_type"),
        chief_complaint_short=payload.get("chief_complaint_short"),
        created_at=datetime.utcnow(),
        ended_at=None,
        is_signed=False,
    )
    db.add(enc)
    db.commit()
    db.refresh(enc)

    return {
        "id": enc.id,
        "patient_id": enc.patient_id,
        "doctor_id": enc.doctor_id,
        "visit_type": enc.visit_type,
        "chief_complaint_short": enc.chief_complaint_short,
        "created_at": enc.created_at.isoformat() if enc.created_at else None,
        "ended_at": enc.ended_at.isoformat() if enc.ended_at else None,
    }


@router.get("/by-patient/{patient_id}")
def list_encounters_by_patient(patient_id: int, db: Session = Depends(get_db), current_doctor: Doctor = Depends(get_current_doctor)):
    # ✅ Todos los médicos pueden ver el historial (según tu regla nueva)
    encs = db.query(Encounter).filter(Encounter.patient_id == patient_id).order_by(Encounter.created_at.desc()).all()
    return [
        {
            "id": e.id,
            "patient_id": e.patient_id,
            "doctor_id": e.doctor_id,
            "visit_type": e.visit_type,
            "chief_complaint_short": e.chief_complaint_short,
            "created_at": e.created_at.isoformat() if e.created_at else None,
            "ended_at": e.ended_at.isoformat() if e.ended_at else None,
        }
        for e in encs
    ]


@router.post("/{encounter_id}/end")
def end_encounter(encounter_id: int, db: Session = Depends(get_db), current_doctor: Doctor = Depends(get_current_doctor)):
    enc = db.query(Encounter).filter(Encounter.id == encounter_id).first()
    if not enc:
        raise HTTPException(status_code=404, detail="Consulta no encontrada")

    # 🔒 Solo el médico dueño puede cerrar SU atención
    if enc.doctor_id != current_doctor.id:
        raise HTTPException(status_code=403, detail="No autorizado")

    if enc.ended_at is None:
        enc.ended_at = datetime.utcnow()
        db.commit()
        db.refresh(enc)

    return {
        "encounter_id": enc.id,
        "ended_at": enc.ended_at.isoformat() if enc.ended_at else None,
        "message": "Atención cerrada ✅",
    }
