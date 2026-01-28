from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from datetime import datetime, timedelta

from ..database import get_db
from ..deps.auth import get_current_doctor
from ..models import Doctor, Encounter, ClinicalNote

router = APIRouter(prefix="/encounters", tags=["Clinical Notes"])


def _can_edit_encounter(enc: Encounter) -> bool:
    # Si está abierta → editable
    if enc.ended_at is None:
        return True
    # Ventana 20 min después de ended_at
    return datetime.utcnow() <= (enc.ended_at + timedelta(minutes=20))


@router.get("/{encounter_id}/note")
def get_note(encounter_id: int, db: Session = Depends(get_db), current_doctor: Doctor = Depends(get_current_doctor)):
    enc = db.query(Encounter).filter(Encounter.id == encounter_id).first()
    if not enc:
        raise HTTPException(status_code=404, detail="Consulta no encontrada")

    # ✅ Todos pueden ver la nota (historial compartido)
    note = db.query(ClinicalNote).filter(ClinicalNote.encounter_id == encounter_id).first()
    if not note:
        return {"encounter_id": encounter_id, "note": None}

    return {
        "encounter_id": encounter_id,
        "note": {
            "id": note.id,
            "chief_complaint": note.chief_complaint,
            "hpi": note.hpi,
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
        },
    }


@router.put("/{encounter_id}/note")
def upsert_note(encounter_id: int, payload: dict, db: Session = Depends(get_db), current_doctor: Doctor = Depends(get_current_doctor)):
    enc = db.query(Encounter).filter(Encounter.id == encounter_id).first()
    if not enc:
        raise HTTPException(status_code=404, detail="Consulta no encontrada")

    # 🔒 Solo el médico dueño puede editar SU nota
    if enc.doctor_id != current_doctor.id:
        raise HTTPException(status_code=403, detail="No autorizado")

    # ⏱️ Ventana de 20 min tras cerrar
    if not _can_edit_encounter(enc):
        raise HTTPException(
            status_code=403,
            detail="Ventana de edición cerrada (20 min). Agrega corrección como Evolución/Addendum."
        )

    note = db.query(ClinicalNote).filter(ClinicalNote.encounter_id == encounter_id).first()
    if not note:
        note = ClinicalNote(encounter_id=encounter_id)
        db.add(note)

    # Campos texto
    for field in [
        "chief_complaint",
        "hpi",
        "physical_exam",
        "complementary_tests",
        "assessment_dx",
        "plan_treatment",
        "indications_alarm_signs",
        "follow_up",
    ]:
        if field in payload:
            setattr(note, field, payload.get(field))

    # Signos vitales
    for field in ["ta_sys", "ta_dia", "hr", "rr", "temp", "spo2"]:
        if field in payload:
            setattr(note, field, payload.get(field))

    db.commit()
    db.refresh(note)

    return {"message": "Nota clínica guardada ✅", "note_id": note.id}
