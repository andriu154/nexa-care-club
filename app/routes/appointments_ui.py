from datetime import datetime, timedelta
from fastapi import APIRouter, Depends, Request, HTTPException, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from starlette.status import HTTP_303_SEE_OTHER

from ..database import get_db
from ..models import Appointment, Patient, Encounter
from .auth import get_logged_doctor

router = APIRouter(tags=["Appointments UI"])
templates = Jinja2Templates(directory="app/templates")


def _redirect_login():
    return RedirectResponse(url="/login", status_code=302)


def _require_login(request: Request, db: Session):
    doc = get_logged_doctor(request, db)
    if not doc:
        return None
    return doc


def _parse_date(s: str | None):
    if not s:
        return None
    try:
        return datetime.strptime(s, "%Y-%m-%d").date()
    except Exception:
        return None


def _overlaps(
    db: Session,
    doctor_id: int,
    start_at: datetime,
    end_at: datetime,
    exclude_id: int | None = None,
) -> bool:
    q = (
        db.query(Appointment)
        .filter(Appointment.doctor_id == doctor_id)
        .filter(Appointment.status != "canceled")
        .filter(Appointment.start_at < end_at)
        .filter(Appointment.end_at > start_at)
    )
    if exclude_id:
        q = q.filter(Appointment.id != exclude_id)
    return db.query(q.exists()).scalar()


def _can_start_now(appt: Appointment) -> bool:
    now = datetime.utcnow()
    start_window = appt.start_at - timedelta(minutes=15)
    end_window = appt.end_at + timedelta(minutes=30)
    return start_window <= now <= end_window


@router.get("/app/appointments/new", response_class=HTMLResponse)
def new_appointment_form(request: Request, db: Session = Depends(get_db), date: str | None = None):
    current_doctor = _require_login(request, db)
    if not current_doctor:
        return _redirect_login()

    d = _parse_date(date)
    if d is None:
        d = datetime.utcnow().date()

    patients = db.query(Patient).order_by(Patient.full_name.asc()).all()

    return templates.TemplateResponse(
        "appointment_new.html",
        {
            "request": request,
            "current_doctor": current_doctor,
            "patients": patients,
            "date": d,
            "error": None,
        },
    )


@router.post("/app/appointments/new")
def create_appointment(
    request: Request,
    db: Session = Depends(get_db),
    patient_id: int = Form(...),
    date: str = Form(...),
    time: str = Form(...),
    duration_min: int = Form(60),
    reason: str = Form(""),
    notes: str = Form(""),
):
    current_doctor = _require_login(request, db)
    if not current_doctor:
        return _redirect_login()

    d = _parse_date(date)
    if d is None:
        raise HTTPException(status_code=400, detail="Fecha inválida")

    try:
        hh, mm = time.split(":")
        start_at = datetime(d.year, d.month, d.day, int(hh), int(mm))
    except Exception:
        raise HTTPException(status_code=400, detail="Hora inválida")

    if start_at < datetime.utcnow() - timedelta(minutes=1):
        patients = db.query(Patient).order_by(Patient.full_name.asc()).all()
        return templates.TemplateResponse(
            "appointment_new.html",
            {
                "request": request,
                "current_doctor": current_doctor,
                "patients": patients,
                "date": d,
                "error": "No puedes agendar una cita en el pasado.",
            },
            status_code=400,
        )

    if duration_min < 10 or duration_min > 240:
        raise HTTPException(status_code=400, detail="Duración inválida (10–240 min)")

    end_at = start_at + timedelta(minutes=duration_min)

    if _overlaps(db, current_doctor.id, start_at, end_at):
        patients = db.query(Patient).order_by(Patient.full_name.asc()).all()
        return templates.TemplateResponse(
            "appointment_new.html",
            {
                "request": request,
                "current_doctor": current_doctor,
                "patients": patients,
                "date": d,
                "error": "Ese horario ya está ocupado. Elige otra hora.",
            },
            status_code=400,
        )

    appt = Appointment(
        doctor_id=current_doctor.id,
        patient_id=patient_id,
        start_at=start_at,
        end_at=end_at,
        status="scheduled",
        reason=(reason or "").strip()[:120] if reason else None,
        notes=(notes or "").strip() if notes else None,
        updated_at=datetime.utcnow(),
    )
    db.add(appt)
    db.commit()

    return RedirectResponse(url=f"/app?date={d.isoformat()}", status_code=HTTP_303_SEE_OTHER)


@router.post("/app/appointments/{appointment_id}/cancel")
def cancel_appointment(appointment_id: int, request: Request, db: Session = Depends(get_db), date: str | None = None):
    current_doctor = _require_login(request, db)
    if not current_doctor:
        return _redirect_login()

    appt = db.query(Appointment).filter(Appointment.id == appointment_id).first()
    if not appt:
        raise HTTPException(status_code=404, detail="Cita no encontrada")

    if appt.doctor_id != current_doctor.id:
        raise HTTPException(status_code=403, detail="No autorizado")

    appt.status = "canceled"
    appt.updated_at = datetime.utcnow()
    db.commit()

    d = _parse_date(date) or datetime.utcnow().date()
    return RedirectResponse(url=f"/app?date={d.isoformat()}", status_code=HTTP_303_SEE_OTHER)


@router.post("/app/appointments/{appointment_id}/reschedule")
def reschedule_appointment(
    appointment_id: int,
    request: Request,
    db: Session = Depends(get_db),
    date: str = Form(...),
    time: str = Form(...),
    duration_min: int = Form(60),
):
    current_doctor = _require_login(request, db)
    if not current_doctor:
        return _redirect_login()

    appt = db.query(Appointment).filter(Appointment.id == appointment_id).first()
    if not appt:
        raise HTTPException(status_code=404, detail="Cita no encontrada")

    if appt.doctor_id != current_doctor.id:
        raise HTTPException(status_code=403, detail="No autorizado")

    d = _parse_date(date)
    if d is None:
        raise HTTPException(status_code=400, detail="Fecha inválida")

    try:
        hh, mm = time.split(":")
        start_at = datetime(d.year, d.month, d.day, int(hh), int(mm))
    except Exception:
        raise HTTPException(status_code=400, detail="Hora inválida")

    if start_at < datetime.utcnow() - timedelta(minutes=1):
        raise HTTPException(status_code=400, detail="No puedes reagendar una cita al pasado")

    if duration_min < 10 or duration_min > 240:
        raise HTTPException(status_code=400, detail="Duración inválida (10–240 min)")

    end_at = start_at + timedelta(minutes=duration_min)

    if _overlaps(db, current_doctor.id, start_at, end_at, exclude_id=appt.id):
        raise HTTPException(status_code=400, detail="Ese horario ya está ocupado")

    appt.start_at = start_at
    appt.end_at = end_at
    appt.updated_at = datetime.utcnow()
    db.commit()

    return RedirectResponse(url=f"/app?date={d.isoformat()}", status_code=HTTP_303_SEE_OTHER)


# =========================
# ✅ INICIAR ATENCIÓN DESDE CITA
# =========================
@router.post("/app/appointments/{appointment_id}/start")
def start_encounter_from_appointment(
    appointment_id: int,
    request: Request,
    db: Session = Depends(get_db),
    date: str | None = None,
):
    current_doctor = _require_login(request, db)
    if not current_doctor:
        return _redirect_login()

    appt = db.query(Appointment).filter(Appointment.id == appointment_id).first()
    if not appt:
        raise HTTPException(status_code=404, detail="Cita no encontrada")

    if appt.doctor_id != current_doctor.id:
        raise HTTPException(status_code=403, detail="No autorizado")

    if appt.status == "canceled":
        raise HTTPException(status_code=400, detail="La cita está cancelada")

    if appt.status == "no_show":
        raise HTTPException(status_code=400, detail="La cita está marcada como No asiste")

    if appt.status == "completed":
        # si ya está atendida pero tiene encounter, abrirlo
        if appt.encounter_id:
            return RedirectResponse(url=f"/app/encounters/{appt.encounter_id}", status_code=HTTP_303_SEE_OTHER)
        raise HTTPException(status_code=400, detail="La cita ya fue atendida")

    # Si ya existe encounter, ir directo
    if appt.encounter_id:
        return RedirectResponse(url=f"/app/encounters/{appt.encounter_id}", status_code=HTTP_303_SEE_OTHER)

    # ⏱️ validar ventana de inicio
    if not _can_start_now(appt):
        raise HTTPException(
            status_code=400,
            detail="Aún no estás dentro de la ventana de atención (15 min antes hasta 30 min después)."
        )

    # Crear encounter y vincularlo
    enc = Encounter(
        patient_id=appt.patient_id,
        doctor_id=current_doctor.id,
        visit_type="Ambulatorio",
        chief_complaint_short=(appt.reason or "")[:120] if appt.reason else "",
        created_at=datetime.utcnow(),
        ended_at=None,
        is_signed=False,
    )
    db.add(enc)
    db.commit()
    db.refresh(enc)

    appt.encounter_id = enc.id
    appt.updated_at = datetime.utcnow()
    db.commit()

    return RedirectResponse(url=f"/app/encounters/{enc.id}", status_code=HTTP_303_SEE_OTHER)


# =========================
# ✅ NO ASISTE (CON MOTIVO OBLIGATORIO)
# =========================
@router.post("/app/appointments/{appointment_id}/no-show")
def mark_no_show(
    appointment_id: int,
    request: Request,
    db: Session = Depends(get_db),
    date: str | None = None,
    reason_no_show: str = Form(...),
):
    current_doctor = _require_login(request, db)
    if not current_doctor:
        return _redirect_login()

    appt = db.query(Appointment).filter(Appointment.id == appointment_id).first()
    if not appt:
        raise HTTPException(status_code=404, detail="Cita no encontrada")

    if appt.doctor_id != current_doctor.id:
        raise HTTPException(status_code=403, detail="No autorizado")

    if appt.status == "completed":
        raise HTTPException(status_code=400, detail="La cita ya fue atendida")

    motivo = (reason_no_show or "").strip()
    if not motivo:
        raise HTTPException(status_code=400, detail="El motivo es obligatorio")

    appt.status = "no_show"
    appt.updated_at = datetime.utcnow()

    # Guardar motivo en notes (sin migraciones)
    stamp = datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")
    entry = f"[{stamp}] NO_SHOW: {motivo}"
    if appt.notes and appt.notes.strip():
        appt.notes = appt.notes.rstrip() + "\n" + entry
    else:
        appt.notes = entry

    db.commit()

    d = _parse_date(date) or datetime.utcnow().date()
    return RedirectResponse(url=f"/app?date={d.isoformat()}", status_code=HTTP_303_SEE_OTHER)
