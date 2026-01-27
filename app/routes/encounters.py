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
from ..models import ClinicalNote  # agrega este import arriba con los otros

@router.get("/{encounter_id}/summary")
def get_encounter_summary(
    encounter_id: int,
    db: Session = Depends(get_db),
    current_doctor: Doctor = Depends(get_current_doctor),
):
    enc = db.query(Encounter).filter(Encounter.id == encounter_id).first()
    if not enc:
        raise HTTPException(status_code=404, detail="Consulta no encontrada")

    # 🔒 Solo el doctor dueño del encounter puede ver el resumen
    if enc.doctor_id != current_doctor.id:
        raise HTTPException(status_code=403, detail="No autorizado")

    patient = db.query(Patient).filter(Patient.id == enc.patient_id).first()
    doctor = db.query(Doctor).filter(Doctor.id == enc.doctor_id).first()
    note = db.query(ClinicalNote).filter(ClinicalNote.encounter_id == encounter_id).first()

    return {
        "encounter": {
            "id": enc.id,
            "patient_id": enc.patient_id,
            "doctor_id": enc.doctor_id,
            "visit_type": enc.visit_type,
            "chief_complaint_short": enc.chief_complaint_short,
        },
        "patient": None if not patient else {
            "id": patient.id,
            "full_name": patient.full_name,
            "qr_code": patient.qr_code,
        },
        "doctor": None if not doctor else {
            "id": doctor.id,
            "name": doctor.name,
        },
        "clinical_note": None if not note else {
            "id": note.id,
            "encounter_id": note.encounter_id,
            "chief_complaint": note.chief_complaint,
            "hpi": note.hpi,
            "past_history": note.past_history,
            "allergies": note.allergies,
            "medications": note.medications,
            "family_history": note.family_history,
            "social_history": note.social_history,
            "review_of_systems": note.review_of_systems,
            "physical_exam": note.physical_exam,
            "complementary_tests": note.complementary_tests,
            "assessment_dx": note.assessment_dx,
            "plan_treatment": note.plan_treatment,
            "indications_alarm_signs": note.indications_alarm_signs,
            "follow_up": note.follow_up,
            "ta_sys": note.ta_sys,
            "ta_dia": note.ta_dia,
            "hr": note.hr,
            "rr": note.rr,
            "temp": note.temp,
            "spo2": note.spo2,
            "weight": note.weight,
            "height": note.height,
            "bmi": note.bmi,
        }
    }
