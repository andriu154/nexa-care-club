from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from typing import List, Optional

from ..database import get_db
from ..deps.auth import get_current_doctor
from ..models import Doctor, Patient, Encounter

router = APIRouter(prefix="/encounters", tags=["Encounters"])


class EncounterCreate(BaseModel):
    patient_id: int
    visit_type: str = Field(pattern="^(primera_vez|control)$")
    chief_complaint_short: Optional[str] = Field(default=None, max_length=200)


class EncounterOut(BaseModel):
    id: int
    patient_id: int
    doctor_id: int
    visit_type: str
    chief_complaint_short: Optional[str] = None

    class Config:
        from_attributes = True


@router.post("", response_model=EncounterOut, status_code=201)
def create_encounter(
    payload: EncounterCreate,
    db: Session = Depends(get_db),
    current_doctor: Doctor = Depends(get_current_doctor),
):
    patient = db.query(Patient).filter(Patient.id == payload.patient_id).first()
    if not patient:
        raise HTTPException(status_code=404, detail="Paciente no encontrado")

    enc = Encounter(
        patient_id=payload.patient_id,
        doctor_id=current_doctor.id,
        visit_type=payload.visit_type,
        chief_complaint_short=payload.chief_complaint_short.strip() if payload.chief_complaint_short else None,
    )

    db.add(enc)
    db.commit()
    db.refresh(enc)
    return enc


@router.get("/by-patient/{patient_id}", response_model=List[EncounterOut])
def list_encounters_by_patient(
    patient_id: int,
    db: Session = Depends(get_db),
    current_doctor: Doctor = Depends(get_current_doctor),
):
    patient = db.query(Patient).filter(Patient.id == patient_id).first()
    if not patient:
        raise HTTPException(status_code=404, detail="Paciente no encontrado")

    return (
        db.query(Encounter)
        .filter(Encounter.patient_id == patient_id)
        .order_by(Encounter.id.desc())
        .all()
    )
