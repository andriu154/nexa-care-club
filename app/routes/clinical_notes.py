from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session
from typing import Optional

from ..database import get_db
from ..deps.auth import get_current_doctor
from ..models import Doctor, Encounter, ClinicalNote

router = APIRouter(prefix="/clinical-notes", tags=["Clinical Notes"])


class ClinicalNoteCreate(BaseModel):
    encounter_id: int

    chief_complaint: Optional[str] = None
    hpi: Optional[str] = None
    past_history: Optional[str] = None
    allergies: Optional[str] = None
    medications: Optional[str] = None
    family_history: Optional[str] = None
    social_history: Optional[str] = None
    review_of_systems: Optional[str] = None
    physical_exam: Optional[str] = None
    complementary_tests: Optional[str] = None
    assessment_dx: Optional[str] = None
    plan_treatment: Optional[str] = None
    indications_alarm_signs: Optional[str] = None
    follow_up: Optional[str] = None

    ta_sys: Optional[int] = None
    ta_dia: Optional[int] = None
    hr: Optional[int] = None
    rr: Optional[int] = None
    temp: Optional[float] = None
    spo2: Optional[int] = None
    weight: Optional[float] = None
    height: Optional[float] = None
    bmi: Optional[float] = None


class ClinicalNoteOut(ClinicalNoteCreate):
    id: int

    class Config:
        from_attributes = True


@router.post("", response_model=ClinicalNoteOut, status_code=201)
def create_or_replace_note(
    payload: ClinicalNoteCreate,
    db: Session = Depends(get_db),
    current_doctor: Doctor = Depends(get_current_doctor),
):
    enc = db.query(Encounter).filter(Encounter.id == payload.encounter_id).first()
    if not enc:
        raise HTTPException(status_code=404, detail="Consulta (encounter) no encontrada")

    # 🔒 Seguridad: solo el doctor que creó la consulta puede escribir la nota
    if enc.doctor_id != current_doctor.id:
        raise HTTPException(status_code=403, detail="No puedes editar una consulta de otro doctor")

    existing = db.query(ClinicalNote).filter(ClinicalNote.encounter_id == payload.encounter_id).first()
    if existing:
        db.delete(existing)
        db.commit()

    note = ClinicalNote(**payload.model_dump())
    db.add(note)
    db.commit()
    db.refresh(note)
    return note


@router.get("/by-encounter/{encounter_id}", response_model=ClinicalNoteOut)
def get_note_by_encounter(
    encounter_id: int,
    db: Session = Depends(get_db),
    current_doctor: Doctor = Depends(get_current_doctor),
):
    note = db.query(ClinicalNote).filter(ClinicalNote.encounter_id == encounter_id).first()
    if not note:
        raise HTTPException(status_code=404, detail="Nota clínica no encontrada")
    return note
