from datetime import datetime, timedelta
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..database import get_db
from ..deps.auth import get_current_doctor
from ..models import Doctor, Encounter, ClinicalNote, EncounterEvolution

router = APIRouter(prefix="/encounters", tags=["Encounters"])

EDIT_WINDOW_MINUTES = 20


def _can_edit(enc: Encounter, current_doctor: Doctor) -> bool:
    if enc.doctor_id != current_doctor.id:
        return False

    # si aún no se ha cerrado, puede editar
    if enc.ended_at is None:
        return True

    return datetime.utcnow() <= (enc.ended_at + timedelta(minutes=EDIT_WINDOW_MINUTES))


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

    return {"ok": True, "encounter_id": enc.id, "ended_at": enc.ended_at.isoformat()}


@router.put("/{encounter_id}/note")
def update_note(
    encounter_id: int,
    payload: dict,
    db: Session = Depends(get_db),
    current_doctor: Doctor = Depends(get_current_doctor),
):
    enc = db.query(Encounter).filter(Encounter.id == encounter_id).first()
    if not enc:
        raise HTTPException(status_code=404, detail="Consulta no encontrada")

    if not _can_edit(enc, current_doctor):
        raise HTTPException(
            status_code=403,
            detail="Ventana de edición cerrada. Agrega correcciones como Evolución/Addendum.",
        )

    note = db.query(ClinicalNote).filter(ClinicalNote.encounter_id == encounter_id).first()
    if not note:
        note = ClinicalNote(encounter_id=encounter_id)
        db.add(note)

    fields = [
        "chief_complaint", "hpi", "physical_exam", "complementary_tests",
        "assessment_dx", "plan_treatment", "indications_alarm_signs", "follow_up",
        "ta_sys", "ta_dia", "hr", "rr", "temp", "spo2"
    ]
    for f in fields:
        if f in payload:
            setattr(note, f, payload[f])

    db.commit()
    db.refresh(note)
    return {"ok": True, "encounter_id": encounter_id}


@router.post("/{encounter_id}/evolutions")
def add_evolution(
    encounter_id: int,
    payload: dict,
    db: Session = Depends(get_db),
    current_doctor: Doctor = Depends(get_current_doctor),
):
    enc = db.query(Encounter).filter(Encounter.id == encounter_id).first()
    if not enc:
        raise HTTPException(status_code=404, detail="Consulta no encontrada")

    content = (payload.get("content") or "").strip()
    if not content:
        raise HTTPException(status_code=400, detail="content es requerido")

    evo = EncounterEvolution(
        encounter_id=encounter_id,
        author_doctor_id=current_doctor.id,
        content=content,
    )
    db.add(evo)
    db.commit()
    db.refresh(evo)

    return {
        "ok": True,
        "evolution_id": evo.id,
        "created_at": evo.created_at.isoformat(),
        "author_doctor_id": evo.author_doctor_id,
    }
