from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from datetime import datetime
import json

from ..database import get_db
from ..deps.auth import get_current_doctor
from ..models import Doctor, Patient, Encounter

router = APIRouter(prefix="/encounters", tags=["Encounters"])


def _normalize_prescription_items(payload: dict) -> str | None:
    raw_items = (
        payload.get("prescription_items")
        or payload.get("recipe_items")
        or payload.get("rx_items")
        or []
    )

    normalized = []

    if isinstance(raw_items, list):
        for item in raw_items:
            if not isinstance(item, dict):
                continue

            prescription = str(
                item.get("prescription")
                or item.get("medication")
                or item.get("medicine")
                or ""
            ).strip()

            indication = str(
                item.get("indication")
                or item.get("instructions")
                or item.get("dose")
                or ""
            ).strip()

            if prescription or indication:
                normalized.append(
                    {
                        "prescription": prescription,
                        "indication": indication,
                    }
                )

    if not normalized:
        return None

    return json.dumps(normalized, ensure_ascii=False)


@router.post("/")
def create_encounter(
    payload: dict,
    db: Session = Depends(get_db),
    current_doctor: Doctor = Depends(get_current_doctor),
):
    patient_id = payload.get("patient_id")
    if not patient_id:
        raise HTTPException(status_code=400, detail="patient_id es requerido")

    patient = db.query(Patient).filter(Patient.id == int(patient_id)).first()
    if not patient:
        raise HTTPException(status_code=404, detail="Paciente no encontrado")

    prescription_json = _normalize_prescription_items(payload)

    enc = Encounter(
        patient_id=patient.id,
        doctor_id=current_doctor.id,
        visit_type=payload.get("visit_type"),
        chief_complaint_short=payload.get("chief_complaint_short"),
        created_at=datetime.utcnow(),
        ended_at=None,
        is_signed=False,
        prescription_json=prescription_json,
    )
    db.add(enc)
    db.commit()
    db.refresh(enc)

    response = {
        "id": enc.id,
        "patient_id": enc.patient_id,
        "doctor_id": enc.doctor_id,
        "visit_type": enc.visit_type,
        "chief_complaint_short": enc.chief_complaint_short,
        "created_at": enc.created_at.isoformat() if enc.created_at else None,
        "ended_at": enc.ended_at.isoformat() if enc.ended_at else None,
        "prescription_items": [],
    }

    if enc.prescription_json:
        try:
            response["prescription_items"] = json.loads(enc.prescription_json)
        except Exception:
            response["prescription_items"] = []

    return response


@router.get("/by-patient/{patient_id}")
def list_encounters_by_patient(
    patient_id: int,
    db: Session = Depends(get_db),
    current_doctor: Doctor = Depends(get_current_doctor),
):
    encs = (
        db.query(Encounter)
        .filter(Encounter.patient_id == patient_id)
        .order_by(Encounter.created_at.desc())
        .all()
    )

    result = []
    for e in encs:
        prescription_items = []
        if e.prescription_json:
            try:
                prescription_items = json.loads(e.prescription_json)
            except Exception:
                prescription_items = []

        result.append(
            {
                "id": e.id,
                "patient_id": e.patient_id,
                "doctor_id": e.doctor_id,
                "visit_type": e.visit_type,
                "chief_complaint_short": e.chief_complaint_short,
                "created_at": e.created_at.isoformat() if e.created_at else None,
                "ended_at": e.ended_at.isoformat() if e.ended_at else None,
                "prescription_items": prescription_items,
            }
        )

    return result


@router.get("/{encounter_id}")
def get_encounter(
    encounter_id: int,
    db: Session = Depends(get_db),
    current_doctor: Doctor = Depends(get_current_doctor),
):
    enc = db.query(Encounter).filter(Encounter.id == encounter_id).first()
    if not enc:
        raise HTTPException(status_code=404, detail="Consulta no encontrada")

    patient = db.query(Patient).filter(Patient.id == enc.patient_id).first()

    prescription_items = []
    if enc.prescription_json:
        try:
            prescription_items = json.loads(enc.prescription_json)
        except Exception:
            prescription_items = []

    return {
        "id": enc.id,
        "patient_id": enc.patient_id,
        "doctor_id": enc.doctor_id,
        "visit_type": enc.visit_type,
        "chief_complaint_short": enc.chief_complaint_short,
        "created_at": enc.created_at.isoformat() if enc.created_at else None,
        "ended_at": enc.ended_at.isoformat() if enc.ended_at else None,
        "is_signed": enc.is_signed,
        "prescription_items": prescription_items,
        "patient": {
            "id": patient.id if patient else None,
            "full_name": getattr(patient, "full_name", None) if patient else None,
            "name": getattr(patient, "name", None) if patient else None,
            "cedula": getattr(patient, "cedula", None) if patient else None,
            "birth_date": patient.birth_date.isoformat() if patient and getattr(patient, "birth_date", None) else None,
        },
    }


@router.post("/{encounter_id}/end")
def end_encounter(
    encounter_id: int,
    db: Session = Depends(get_db),
    current_doctor: Doctor = Depends(get_current_doctor),
):
    enc = db.query(Encounter).filter(Encounter.id == encounter_id).first()
    if not enc:
        raise HTTPException(status_code=404, detail="Consulta no encontrada")

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