from fastapi import APIRouter, Depends, Request, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from datetime import datetime, timedelta

from ..database import get_db
from ..deps.auth import get_current_doctor
from ..models import Patient, Encounter, Doctor, ClinicalNote, EncounterEvolution

router = APIRouter(tags=["UI"])
templates = Jinja2Templates(directory="app/templates")


def _is_editable(enc: Encounter) -> bool:
    # Si está abierta: editable
    if enc.ended_at is None:
        return True
    # Si cerró: editable solo 20 min
    return datetime.utcnow() <= (enc.ended_at + timedelta(minutes=20))


@router.get("/app", response_class=HTMLResponse)
def ui_home(request: Request):
    return RedirectResponse(url="/app/patients", status_code=302)


@router.get("/app/patients", response_class=HTMLResponse)
def ui_patients(request: Request, db: Session = Depends(get_db), current_doctor: Doctor = Depends(get_current_doctor)):
    patients = db.query(Patient).order_by(Patient.id.desc()).all()
    return templates.TemplateResponse(
        "patients.html",
        {"request": request, "current_doctor": current_doctor, "patients": patients},
    )


@router.get("/app/patients/{patient_id}", response_class=HTMLResponse)
def ui_patient_detail(patient_id: int, request: Request, db: Session = Depends(get_db), current_doctor: Doctor = Depends(get_current_doctor)):
    patient = db.query(Patient).filter(Patient.id == patient_id).first()
    if not patient:
        raise HTTPException(status_code=404, detail="Paciente no encontrado")

    encounters = (
        db.query(Encounter)
        .filter(Encounter.patient_id == patient_id)
        .order_by(Encounter.created_at.desc(), Encounter.id.desc())
        .all()
    )

    items = []
    for enc in encounters:
        doc = db.query(Doctor).filter(Doctor.id == enc.doctor_id).first()
        items.append(
            {
                "enc": enc,
                "doc": doc,
                "pdf_url": f"/encounters/{enc.id}/pdf",
            }
        )

    return templates.TemplateResponse(
        "patient_detail.html",
        {
            "request": request,
            "current_doctor": current_doctor,
            "patient": patient,
            "items": items,
            "pdf_consolidated_url": f"/patients/{patient.id}/history/pdf",
        },
    )


@router.post("/app/patients/{patient_id}/new-encounter")
def ui_new_encounter(patient_id: int, db: Session = Depends(get_db), current_doctor: Doctor = Depends(get_current_doctor)):
    patient = db.query(Patient).filter(Patient.id == patient_id).first()
    if not patient:
        raise HTTPException(status_code=404, detail="Paciente no encontrado")

    enc = Encounter(
        patient_id=patient.id,
        doctor_id=current_doctor.id,
        visit_type="Ambulatorio",
        chief_complaint_short="",
        created_at=datetime.utcnow(),
        ended_at=None,
        is_signed=False,
    )
    db.add(enc)
    db.commit()
    db.refresh(enc)

    return RedirectResponse(url=f"/app/encounters/{enc.id}", status_code=302)


@router.get("/app/encounters/{encounter_id}", response_class=HTMLResponse)
def ui_encounter(encounter_id: int, request: Request, db: Session = Depends(get_db), current_doctor: Doctor = Depends(get_current_doctor)):
    enc = db.query(Encounter).filter(Encounter.id == encounter_id).first()
    if not enc:
        raise HTTPException(status_code=404, detail="Consulta no encontrada")

    patient = db.query(Patient).filter(Patient.id == enc.patient_id).first()
    doc = db.query(Doctor).filter(Doctor.id == enc.doctor_id).first()

    note = db.query(ClinicalNote).filter(ClinicalNote.encounter_id == encounter_id).first()
    evols = (
        db.query(EncounterEvolution)
        .filter(EncounterEvolution.encounter_id == encounter_id)
        .order_by(EncounterEvolution.created_at.asc())
        .all()
    )

    editable_window = _is_editable(enc)
    is_owner = (enc.doctor_id == current_doctor.id)
    can_edit_note = is_owner and editable_window

    return templates.TemplateResponse(
        "encounter.html",
        {
            "request": request,
            "current_doctor": current_doctor,
            "enc": enc,
            "patient": patient,
            "doc": doc,
            "note": note,
            "evols": evols,
            "editable": editable_window,
            "is_owner": is_owner,
            "can_edit_note": can_edit_note,
            "pdf_url": f"/encounters/{enc.id}/pdf",
        },
    )


@router.post("/app/encounters/{encounter_id}/save-note")
async def ui_save_note(encounter_id: int, request: Request, db: Session = Depends(get_db), current_doctor: Doctor = Depends(get_current_doctor)):
    enc = db.query(Encounter).filter(Encounter.id == encounter_id).first()
    if not enc:
        raise HTTPException(status_code=404, detail="Consulta no encontrada")

    # 🔒 solo el dueño puede editar SU nota
    if enc.doctor_id != current_doctor.id:
        raise HTTPException(status_code=403, detail="No autorizado")

    # ⏱️ ventana 20 min
    if not _is_editable(enc):
        raise HTTPException(
            status_code=403,
            detail="Ventana de edición cerrada (20 min). Usa Evolución/Addendum para correcciones."
        )

    form = await request.form()

    # Guardar resumen corto en Encounter (opcional, pero premium)
    enc.chief_complaint_short = (form.get("chief_complaint_short") or "").strip()[:120]
    enc.visit_type = (form.get("visit_type") or enc.visit_type or "Ambulatorio").strip()[:50]

    note = db.query(ClinicalNote).filter(ClinicalNote.encounter_id == encounter_id).first()
    if not note:
        note = ClinicalNote(encounter_id=encounter_id)
        db.add(note)

    # Textos
    note.chief_complaint = (form.get("chief_complaint") or "").strip()
    note.hpi = (form.get("hpi") or "").strip()
    note.physical_exam = (form.get("physical_exam") or "").strip()
    note.complementary_tests = (form.get("complementary_tests") or "").strip()
    note.assessment_dx = (form.get("assessment_dx") or "").strip()
    note.plan_treatment = (form.get("plan_treatment") or "").strip()
    note.indications_alarm_signs = (form.get("indications_alarm_signs") or "").strip()
    note.follow_up = (form.get("follow_up") or "").strip()

    # Signos vitales helpers
    def to_int(v):
        v = (v or "").strip()
        if v == "":
            return None
        try:
            return int(v)
        except Exception:
            return None

    note.ta_sys = to_int(form.get("ta_sys"))
    note.ta_dia = to_int(form.get("ta_dia"))
    note.hr = to_int(form.get("hr"))
    note.rr = to_int(form.get("rr"))
    note.spo2 = to_int(form.get("spo2"))

    temp = (form.get("temp") or "").strip()
    note.temp = temp if temp else None

    db.commit()

    return RedirectResponse(url=f"/app/encounters/{encounter_id}", status_code=302)


@router.post("/app/encounters/{encounter_id}/end")
def ui_end_encounter(encounter_id: int, db: Session = Depends(get_db), current_doctor: Doctor = Depends(get_current_doctor)):
    enc = db.query(Encounter).filter(Encounter.id == encounter_id).first()
    if not enc:
        raise HTTPException(status_code=404, detail="Consulta no encontrada")

    if enc.doctor_id != current_doctor.id:
        raise HTTPException(status_code=403, detail="No autorizado")

    if enc.ended_at is None:
        enc.ended_at = datetime.utcnow()
        db.commit()

    return RedirectResponse(url=f"/app/encounters/{encounter_id}", status_code=302)


@router.post("/app/encounters/{encounter_id}/add-evolution")
async def ui_add_evolution(encounter_id: int, request: Request, db: Session = Depends(get_db), current_doctor: Doctor = Depends(get_current_doctor)):
    enc = db.query(Encounter).filter(Encounter.id == encounter_id).first()
    if not enc:
        raise HTTPException(status_code=404, detail="Consulta no encontrada")

    form = await request.form()
    content = (form.get("content") or "").strip()
    if not content:
        return RedirectResponse(url=f"/app/encounters/{encounter_id}", status_code=302)

    ev = EncounterEvolution(
        encounter_id=encounter_id,
        author_doctor_id=current_doctor.id,
        content=content,
    )
    db.add(ev)
    db.commit()

    return RedirectResponse(url=f"/app/encounters/{encounter_id}", status_code=302)
