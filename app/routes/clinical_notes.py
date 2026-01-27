from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session
from typing import Optional, List

from ..database import get_db
from ..deps.auth import get_current_doctor
from ..models import Doctor, Encounter, ClinicalNote

router = APIRouter(prefix="/clinical-notes", tags=["Clinical Notes"])


# -----------------------------
# Schemas
# -----------------------------
class ClinicalNoteCreate(BaseModel):
    encounter_id: int

    # Texto libre (MG)
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

    # Signos vitales
    ta_sys: Optional[int] = None
    ta_dia: Optional[int] = None
    hr: Optional[int] = None
    rr: Optional[int] = None
    temp: Optional[float] = None
    spo2: Optional[int] = None
    weight: Optional[float] = None
    height: Optional[float] = None
    bmi: Optional[float] = None

    # ✅ Plantilla MG estructurada (listas)
    diagnoses_list: Optional[List[str]] = None
    medications_list: Optional[List[str]] = None
    tests_list: Optional[List[str]] = None
    plan_list: Optional[List[str]] = None


class ClinicalNoteOut(ClinicalNoteCreate):
    id: int

    class Config:
        from_attributes = True


# -----------------------------
# Helpers
# -----------------------------
def _bullets(items: Optional[List[str]]) -> Optional[str]:
    if not items:
        return None
    cleaned = [i.strip() for i in items if i and i.strip()]
    if not cleaned:
        return None
    return "\n".join([f"• {i}" for i in cleaned])


def _append_section(existing_text: Optional[str], bullets_text: Optional[str]) -> Optional[str]:
    """
    Si hay texto libre, lo conserva y agrega debajo las viñetas.
    Si no hay texto libre, usa solo las viñetas.
    """
    if not bullets_text:
        return existing_text
    if existing_text and existing_text.strip():
        return existing_text.strip() + "\n" + bullets_text
    return bullets_text


# -----------------------------
# Endpoints
# -----------------------------
@router.post("", response_model=ClinicalNoteOut, status_code=201)
def create_or_replace_note(
    payload: ClinicalNoteCreate,
    db: Session = Depends(get_db),
    current_doctor: Doctor = Depends(get_current_doctor),
):
    # 1) validar encounter
    enc = db.query(Encounter).filter(Encounter.id == payload.encounter_id).first()
    if not enc:
        raise HTTPException(status_code=404, detail="Consulta (encounter) no encontrada")

    # 2) seguridad: solo doctor dueño
    if enc.doctor_id != current_doctor.id:
        raise HTTPException(status_code=403, detail="No puedes editar una consulta de otro doctor")

    # 3) convertir listas a texto con viñetas y anexar a campos existentes
    dx_text = _bullets(payload.diagnoses_list)
    meds_text = _bullets(payload.medications_list)
    tests_text = _bullets(payload.tests_list)
    plan_text = _bullets(payload.plan_list)

    payload.assessment_dx = _append_section(payload.assessment_dx, dx_text)
    payload.medications = _append_section(payload.medications, meds_text)
    payload.complementary_tests = _append_section(payload.complementary_tests, tests_text)
    payload.plan_treatment = _append_section(payload.plan_treatment, plan_text)

    # 4) si ya existe nota, la reemplazamos
    existing = db.query(ClinicalNote).filter(ClinicalNote.encounter_id == payload.encounter_id).first()
    if existing:
        db.delete(existing)
        db.commit()

    # 5) crear nota filtrando campos que NO existen en la DB
    data = payload.model_dump()
    data.pop("diagnoses_list", None)
    data.pop("medications_list", None)
    data.pop("tests_list", None)
    data.pop("plan_list", None)

    note = ClinicalNote(**data)
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
