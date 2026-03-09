from datetime import datetime, timedelta
import secrets
import os
from zoneinfo import ZoneInfo

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

APP_TZ = ZoneInfo(os.getenv("APP_TIMEZONE", "America/Guayaquil"))


def _now_local() -> datetime:
    return datetime.now(APP_TZ)


def _redirect_login():
    return RedirectResponse(url="/login", status_code=302)


def _require_login(request: Request, db: Session):
    return get_logged_doctor(request, db)


def _parse_date(s: str | None):
    if not s:
        return None
    try:
        return datetime.strptime(s, "%Y-%m-%d").date()
    except Exception:
        return None


def _clean_cedula(s: str) -> str:
    return "".join(ch for ch in (s or "") if ch.isdigit()).strip()


def _find_patient_by_cedula(db: Session, cedula: str):
    ced = _clean_cedula(cedula or "")
    if not ced:
        return None
    return db.query(Patient).filter(Patient.cedula == ced).first()


def _generate_qr_code(db: Session) -> str:
    while True:
        code = "QR-" + secrets.token_hex(4).upper()
        exists = db.query(Patient).filter(Patient.qr_code == code).first()
        if not exists:
            return code


def _overlaps(
    db: Session,
    doctor_id: int,
    start_at_naive: datetime,
    end_at_naive: datetime,
    exclude_id: int | None = None,
) -> bool:
    q = (
        db.query(Appointment)
        .filter(Appointment.doctor_id == doctor_id)
        .filter(Appointment.status != "canceled")
        .filter(Appointment.start_at < end_at_naive)
        .filter(Appointment.end_at > start_at_naive)
    )
    if exclude_id:
        q = q.filter(Appointment.id != exclude_id)
    return db.query(q.exists()).scalar()


def _can_start_now(appt: Appointment) -> bool:
    now_local_naive = _now_local().replace(tzinfo=None)
    start_window = appt.start_at - timedelta(minutes=15)
    end_window = appt.end_at + timedelta(minutes=30)
    return start_window <= now_local_naive <= end_window


def _is_modal_request(request: Request, modal_param: str | int | None) -> bool:
    if str(modal_param or "").strip() == "1":
        return True
    hdr = (request.headers.get("X-Requested-With") or "").lower()
    return hdr == "fetch"


@router.get("/app/appointments/new", response_class=HTMLResponse)
def new_appointment_form(
    request: Request,
    db: Session = Depends(get_db),
    date: str | None = None,
    cedula: str | None = None,
    modal: str | None = None,
):
    current_doctor = _require_login(request, db)
    if not current_doctor:
        return _redirect_login()

    d = _parse_date(date) or _now_local().date()
    ced = _clean_cedula(cedula or "")
    patient = _find_patient_by_cedula(db, ced) if ced else None

    ctx = {
        "request": request,
        "current_doctor": current_doctor,
        "date": d.isoformat(),
        "cedula": ced,
        "patient_found": patient,
        "error": None,
        "time": "",
        "duration_min": 60,
        "reason": "",
        "notes": "",
    }

    if _is_modal_request(request, modal):
        return templates.TemplateResponse("appointment_new_modal.html", ctx)

    return templates.TemplateResponse("appointment_new.html", ctx)


@router.post("/app/patients/quick-create")
def quick_create_patient(
    request: Request,
    db: Session = Depends(get_db),
    date: str = Form(...),
    cedula: str = Form(...),
    full_name: str = Form(...),
    phone: str = Form(""),
    modal: str = Form("0"),
):
    current_doctor = _require_login(request, db)
    if not current_doctor:
        return _redirect_login()

    d = _parse_date(date) or _now_local().date()

    ced = _clean_cedula(cedula)
    if not ced:
        raise HTTPException(status_code=400, detail="Cédula inválida")

    name = (full_name or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="Nombre completo es obligatorio")

    existing = _find_patient_by_cedula(db, ced)
    if existing:
        suffix = "&modal=1" if str(modal) == "1" else ""
        return RedirectResponse(
            url=f"/app/appointments/new?date={d.isoformat()}&cedula={ced}{suffix}",
            status_code=HTTP_303_SEE_OTHER,
        )

    now_local_naive = _now_local().replace(tzinfo=None)

    p = Patient(
        cedula=ced,
        full_name=name,
        phone=(phone or "").strip() or None,
        qr_code=_generate_qr_code(db),
        total_sessions=0,
        completed_sessions=0,
        status="Activo",
        created_at=now_local_naive,
        updated_at=now_local_naive,
    )
    db.add(p)
    db.commit()
    db.refresh(p)

    suffix = "&modal=1" if str(modal) == "1" else ""
    return RedirectResponse(
        url=f"/app/appointments/new?date={d.isoformat()}&cedula={ced}{suffix}",
        status_code=HTTP_303_SEE_OTHER,
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
    modal: str = Form("0"),
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

    now_local_naive = _now_local().replace(tzinfo=None)

    if start_at < now_local_naive - timedelta(minutes=1):
        raise HTTPException(status_code=400, detail="No puedes agendar una cita en el pasado.")

    if duration_min < 10 or duration_min > 240:
        raise HTTPException(status_code=400, detail="Duración inválida (10–240 min)")

    patient = db.query(Patient).filter(Patient.id == patient_id).first()
    if not patient:
        raise HTTPException(status_code=400, detail="Paciente inválido")

    end_at = start_at + timedelta(minutes=duration_min)

    if _overlaps(db, current_doctor.id, start_at, end_at):
        raise HTTPException(status_code=400, detail="Ese horario ya está ocupado.")

    appt = Appointment(
        doctor_id=current_doctor.id,
        patient_id=patient_id,
        start_at=start_at,
        end_at=end_at,
        status="scheduled",
        reason=(reason or "").strip()[:120] if reason else None,
        notes=(notes or "").strip() if notes else None,
        updated_at=now_local_naive,
    )
    db.add(appt)
    db.commit()
    db.refresh(appt)

    return RedirectResponse(url=f"/app?date={d.isoformat()}", status_code=HTTP_303_SEE_OTHER)


@router.post("/app/appointments/{appointment_id}/cancel")
def cancel_appointment(
    appointment_id: int,
    request: Request,
    db: Session = Depends(get_db),
    date: str | None = None,
):
    current_doctor = _require_login(request, db)
    if not current_doctor:
        return _redirect_login()

    appt = (
        db.query(Appointment)
        .filter(Appointment.id == appointment_id)
        .filter(Appointment.doctor_id == current_doctor.id)
        .first()
    )
    if not appt:
        raise HTTPException(status_code=404, detail="Cita no encontrada")

    appt.status = "canceled"
    appt.updated_at = _now_local().replace(tzinfo=None)
    db.commit()

    d = _parse_date(date) or _now_local().date()
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

    appt = (
        db.query(Appointment)
        .filter(Appointment.id == appointment_id)
        .filter(Appointment.doctor_id == current_doctor.id)
        .first()
    )
    if not appt:
        raise HTTPException(status_code=404, detail="Cita no encontrada")

    d = _parse_date(date)
    if d is None:
        raise HTTPException(status_code=400, detail="Fecha inválida")

    try:
        hh, mm = time.split(":")
        start_at = datetime(d.year, d.month, d.day, int(hh), int(mm))
    except Exception:
        raise HTTPException(status_code=400, detail="Hora inválida")

    now_local_naive = _now_local().replace(tzinfo=None)

    if start_at < now_local_naive - timedelta(minutes=1):
        raise HTTPException(status_code=400, detail="No puedes reagendar una cita al pasado")

    if duration_min < 10 or duration_min > 240:
        raise HTTPException(status_code=400, detail="Duración inválida (10–240 min)")

    end_at = start_at + timedelta(minutes=duration_min)

    if _overlaps(db, current_doctor.id, start_at, end_at, exclude_id=appt.id):
        raise HTTPException(status_code=400, detail="Ese horario ya está ocupado")

    appt.start_at = start_at
    appt.end_at = end_at
    appt.updated_at = now_local_naive
    db.commit()

    return RedirectResponse(url=f"/app?date={d.isoformat()}", status_code=HTTP_303_SEE_OTHER)


@router.post("/app/appointments/{appointment_id}/start")
def start_encounter_from_appointment(
    appointment_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    current_doctor = _require_login(request, db)
    if not current_doctor:
        return _redirect_login()

    appt = (
        db.query(Appointment)
        .filter(Appointment.id == appointment_id)
        .filter(Appointment.doctor_id == current_doctor.id)
        .first()
    )
    if not appt:
        raise HTTPException(status_code=404, detail="Cita no encontrada")

    if appt.status == "canceled":
        raise HTTPException(status_code=400, detail="La cita está cancelada")

    if appt.status == "no_show":
        raise HTTPException(status_code=400, detail="La cita está marcada como No asiste")

    if appt.status == "completed":
        if appt.encounter_id:
            existing_completed = db.query(Encounter).filter(Encounter.id == appt.encounter_id).first()
            if existing_completed:
                return RedirectResponse(
                    url=f"/app/encounters/{existing_completed.id}",
                    status_code=HTTP_303_SEE_OTHER,
                )
        raise HTTPException(status_code=400, detail="La cita ya fue atendida")

    if appt.encounter_id:
        existing_enc = db.query(Encounter).filter(Encounter.id == appt.encounter_id).first()
        if existing_enc:
            return RedirectResponse(
                url=f"/app/encounters/{existing_enc.id}",
                status_code=HTTP_303_SEE_OTHER,
            )
        appt.encounter_id = None
        appt.updated_at = _now_local().replace(tzinfo=None)
        db.commit()
        db.refresh(appt)

    if not _can_start_now(appt):
        raise HTTPException(
            status_code=400,
            detail="Aún no estás dentro de la ventana de atención (15 min antes hasta 30 min después)."
        )

    now_local_naive = _now_local().replace(tzinfo=None)

    enc = Encounter(
        patient_id=appt.patient_id,
        doctor_id=current_doctor.id,
        visit_type="Ambulatorio",
        chief_complaint_short=((appt.reason or "").strip())[:120],
        created_at=now_local_naive,
        ended_at=None,
        is_signed=False,
    )
    db.add(enc)
    db.commit()
    db.refresh(enc)

    appt.encounter_id = enc.id
    appt.status = "confirmed"
    appt.updated_at = now_local_naive
    db.commit()

    return RedirectResponse(url=f"/app/encounters/{enc.id}", status_code=HTTP_303_SEE_OTHER)


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

    appt = (
        db.query(Appointment)
        .filter(Appointment.id == appointment_id)
        .filter(Appointment.doctor_id == current_doctor.id)
        .first()
    )
    if not appt:
        raise HTTPException(status_code=404, detail="Cita no encontrada")

    if appt.status == "completed":
        raise HTTPException(status_code=400, detail="La cita ya fue atendida")

    motivo = (reason_no_show or "").strip()
    if not motivo:
        raise HTTPException(status_code=400, detail="El motivo es obligatorio")

    appt.status = "no_show"
    appt.updated_at = _now_local().replace(tzinfo=None)

    stamp = _now_local().strftime("%Y-%m-%d %H:%M %Z")
    entry = f"[{stamp}] NO_SHOW: {motivo}"
    if appt.notes and appt.notes.strip():
        appt.notes = appt.notes.rstrip() + "\n" + entry
    else:
        appt.notes = entry

    db.commit()

    d = _parse_date(date) or _now_local().date()
    return RedirectResponse(url=f"/app?date={d.isoformat()}", status_code=HTTP_303_SEE_OTHER)