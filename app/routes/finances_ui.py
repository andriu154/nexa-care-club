# app/routes/finances_ui.py
from datetime import datetime
import os
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session, joinedload

from ..database import get_db
from ..models import Charge, Doctor, Encounter, Patient, ServiceCatalog
from .auth import get_logged_doctor, is_admin

router = APIRouter(prefix="/app/finances", tags=["Finances UI"])
templates = Jinja2Templates(directory="app/templates")

APP_TZ = ZoneInfo(os.getenv("APP_TIMEZONE", "America/Guayaquil"))


def _redirect_login():
    return RedirectResponse(url="/login", status_code=302)


def _redirect_app():
    return RedirectResponse(url="/app", status_code=302)


def _now_local_naive() -> datetime:
    return datetime.now(APP_TZ).replace(tzinfo=None)


def _month_bounds(month_str: str | None):
    today = datetime.now(APP_TZ).date()

    if month_str:
        try:
            base = datetime.strptime(month_str, "%Y-%m").date()
        except Exception:
            base = today.replace(day=1)
    else:
        base = today.replace(day=1)

    start = datetime(base.year, base.month, 1, 0, 0, 0)
    if base.month == 12:
        next_month = datetime(base.year + 1, 1, 1, 0, 0, 0)
    else:
        next_month = datetime(base.year, base.month + 1, 1, 0, 0, 0)

    return start, next_month, base.strftime("%Y-%m")


def _to_float(value) -> float:
    try:
        return round(float(value or 0), 2)
    except Exception:
        return 0.0


def _parse_int(value):
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        return int(raw)
    except Exception:
        return None


def _parse_money(value) -> float:
    raw = str(value or "").strip().replace(",", ".")
    if not raw:
        return 0.0
    try:
        return round(float(raw), 2)
    except Exception:
        return 0.0


def _render_finances(
    request: Request,
    current_doctor: Doctor,
    db: Session,
    error: str | None = None,
    success: str | None = None,
):
    if not is_admin(current_doctor):
        return _redirect_app()

    month = (request.query_params.get("month") or "").strip()
    selected_doctor_id = _parse_int(request.query_params.get("doctor_id"))
    selected_service_id = _parse_int(request.query_params.get("service_id"))
    selected_status = (request.query_params.get("payment_status") or "").strip().lower()
    selected_method = (request.query_params.get("payment_method") or "").strip().lower()
    preselected_patient_id = _parse_int(request.query_params.get("patient_id"))
    preselected_encounter_id = _parse_int(request.query_params.get("encounter_id"))

    month_start, month_end, selected_month = _month_bounds(month)

    charges_query = (
        db.query(Charge)
        .options(
            joinedload(Charge.patient),
            joinedload(Charge.doctor),
            joinedload(Charge.service),
        )
        .filter(Charge.charge_date >= month_start)
        .filter(Charge.charge_date < month_end)
    )

    if selected_doctor_id:
        charges_query = charges_query.filter(Charge.doctor_id == selected_doctor_id)

    if selected_service_id:
        charges_query = charges_query.filter(Charge.service_id == selected_service_id)

    if selected_status:
        charges_query = charges_query.filter(Charge.payment_status == selected_status)

    if selected_method:
        charges_query = charges_query.filter(Charge.payment_method == selected_method)

    month_charges = charges_query.order_by(Charge.charge_date.desc(), Charge.id.desc()).all()

    today_local = datetime.now(APP_TZ).date()

    paid_total = sum(_to_float(c.total) for c in month_charges if c.payment_status == "pagado")
    pending_total = sum(_to_float(c.total) for c in month_charges if c.payment_status == "pendiente")
    canceled_total = sum(_to_float(c.total) for c in month_charges if c.payment_status == "anulado")
    paid_today = sum(
        _to_float(c.total)
        for c in month_charges
        if c.payment_status == "pagado" and c.charge_date and c.charge_date.date() == today_local
    )
    paid_count = sum(1 for c in month_charges if c.payment_status == "pagado")
    avg_ticket = round((paid_total / paid_count), 2) if paid_count else 0.0

    doctor_ranking = {}
    service_ranking = {}

    for c in month_charges:
        if c.payment_status != "pagado":
            continue

        doctor_name = c.doctor.name if c.doctor else "Sin profesional"
        doctor_ranking.setdefault(doctor_name, 0.0)
        doctor_ranking[doctor_name] += _to_float(c.total)

        service_name = c.service.name if c.service else (c.description or "Sin servicio")
        service_ranking.setdefault(service_name, 0.0)
        service_ranking[service_name] += _to_float(c.total)

    ranking_doctors = sorted(doctor_ranking.items(), key=lambda x: x[1], reverse=True)
    ranking_services = sorted(service_ranking.items(), key=lambda x: x[1], reverse=True)

    recent_charges = month_charges[:30]

    patients = db.query(Patient).order_by(Patient.full_name.asc()).all()
    doctors = db.query(Doctor).filter(Doctor.is_active == True).order_by(Doctor.name.asc()).all()
    services = db.query(ServiceCatalog).order_by(ServiceCatalog.is_active.desc(), ServiceCatalog.name.asc()).all()

    selected_patient = None
    selected_encounter = None
    if preselected_patient_id:
        selected_patient = db.query(Patient).filter(Patient.id == preselected_patient_id).first()

    if preselected_encounter_id:
        selected_encounter = db.query(Encounter).filter(Encounter.id == preselected_encounter_id).first()
        if selected_encounter and not selected_patient:
            selected_patient = db.query(Patient).filter(Patient.id == selected_encounter.patient_id).first()
            preselected_patient_id = selected_encounter.patient_id

    form_defaults = {
        "patient_id": preselected_patient_id or "",
        "doctor_id": selected_encounter.doctor_id if selected_encounter else "",
        "service_id": "",
        "description": "",
        "subtotal": "",
        "discount": "0.00",
        "payment_method": "efectivo",
        "payment_status": "pagado",
        "charge_date": today_local.strftime("%Y-%m-%d"),
        "notes": "",
        "encounter_id": preselected_encounter_id or "",
    }

    return templates.TemplateResponse(
        "finances.html",
        {
            "request": request,
            "current_doctor": current_doctor,
            "error": error,
            "success": success,
            "selected_month": selected_month,
            "selected_doctor_id": selected_doctor_id,
            "selected_service_id": selected_service_id,
            "selected_status": selected_status,
            "selected_method": selected_method,
            "summary": {
                "paid_total": round(paid_total, 2),
                "pending_total": round(pending_total, 2),
                "canceled_total": round(canceled_total, 2),
                "paid_today": round(paid_today, 2),
                "avg_ticket": round(avg_ticket, 2),
                "charge_count": len(month_charges),
            },
            "recent_charges": recent_charges,
            "ranking_doctors": ranking_doctors,
            "ranking_services": ranking_services,
            "patients": patients,
            "doctors": doctors,
            "services": services,
            "form_defaults": form_defaults,
            "selected_patient": selected_patient,
            "selected_encounter": selected_encounter,
        },
    )


@router.get("", response_class=HTMLResponse)
@router.get("/", response_class=HTMLResponse)
def finances_page(request: Request, db: Session = Depends(get_db)):
    current_doctor = get_logged_doctor(request, db)
    if not current_doctor:
        return _redirect_login()
    return _render_finances(request, current_doctor, db)


@router.post("/services/create")
def create_service(
    request: Request,
    db: Session = Depends(get_db),
    name: str = Form(...),
    category: str = Form("Consulta"),
    base_price: str = Form(...),
):
    current_doctor = get_logged_doctor(request, db)
    if not current_doctor:
        return _redirect_login()
    if not is_admin(current_doctor):
        return _redirect_app()

    name = (name or "").strip()
    category = (category or "Consulta").strip()
    price = _parse_money(base_price)

    if not name:
        return _render_finances(request, current_doctor, db, error="El nombre del servicio es obligatorio.")

    if price < 0:
        return _render_finances(request, current_doctor, db, error="El precio no puede ser negativo.")

    existing = db.query(ServiceCatalog).filter(ServiceCatalog.name == name).first()
    if existing:
        existing.category = category or existing.category
        existing.base_price = price
        existing.is_active = True
        existing.updated_at = datetime.utcnow()
        db.commit()
        return _render_finances(request, current_doctor, db, success=f"Servicio actualizado: {name}")

    item = ServiceCatalog(
        name=name,
        category=category,
        base_price=price,
        is_active=True,
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
    )
    db.add(item)
    db.commit()

    return _render_finances(request, current_doctor, db, success=f"Servicio creado: {name}")


@router.post("/charges/create")
def create_charge(
    request: Request,
    db: Session = Depends(get_db),
    patient_id: int = Form(...),
    doctor_id: str = Form(""),
    service_id: str = Form(""),
    encounter_id: str = Form(""),
    description: str = Form(""),
    subtotal: str = Form(...),
    discount: str = Form("0"),
    payment_method: str = Form("efectivo"),
    payment_status: str = Form("pagado"),
    charge_date: str = Form(""),
    notes: str = Form(""),
):
    current_doctor = get_logged_doctor(request, db)
    if not current_doctor:
        return _redirect_login()
    if not is_admin(current_doctor):
        return _redirect_app()

    patient = db.query(Patient).filter(Patient.id == patient_id).first()
    if not patient:
        return _render_finances(request, current_doctor, db, error="Paciente no encontrado.")

    parsed_doctor_id = _parse_int(doctor_id)
    parsed_service_id = _parse_int(service_id)
    parsed_encounter_id = _parse_int(encounter_id)

    doctor = db.query(Doctor).filter(Doctor.id == parsed_doctor_id).first() if parsed_doctor_id else None
    service = db.query(ServiceCatalog).filter(ServiceCatalog.id == parsed_service_id).first() if parsed_service_id else None
    encounter = db.query(Encounter).filter(Encounter.id == parsed_encounter_id).first() if parsed_encounter_id else None

    subtotal_value = _parse_money(subtotal)
    discount_value = _parse_money(discount)

    if subtotal_value <= 0 and service:
        subtotal_value = _to_float(service.base_price)

    if subtotal_value <= 0:
        return _render_finances(request, current_doctor, db, error="El subtotal debe ser mayor a 0.")

    if discount_value < 0:
        return _render_finances(request, current_doctor, db, error="El descuento no puede ser negativo.")

    total_value = round(max(0.0, subtotal_value - discount_value), 2)

    payment_method = (payment_method or "efectivo").strip().lower()
    if payment_method not in {"efectivo", "transferencia", "tarjeta", "mixto", "otros"}:
        payment_method = "efectivo"

    payment_status = (payment_status or "pagado").strip().lower()
    if payment_status not in {"pagado", "pendiente", "anulado"}:
        payment_status = "pagado"

    description = (description or "").strip()
    if not description and service:
        description = service.name

    if not description:
        description = "Cobro clínico"

    charge_dt = _now_local_naive()
    raw_charge_date = (charge_date or "").strip()
    if raw_charge_date:
        try:
            parsed_date = datetime.strptime(raw_charge_date, "%Y-%m-%d").date()
            charge_dt = datetime(parsed_date.year, parsed_date.month, parsed_date.day, 12, 0, 0)
        except Exception:
            pass

    charge = Charge(
        patient_id=patient.id,
        doctor_id=doctor.id if doctor else None,
        service_id=service.id if service else None,
        encounter_id=encounter.id if encounter else None,
        description=description,
        subtotal=subtotal_value,
        discount=discount_value,
        total=total_value,
        payment_method=payment_method,
        payment_status=payment_status,
        charge_date=charge_dt,
        notes=(notes or "").strip() or None,
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
    )
    db.add(charge)
    db.commit()

    return _render_finances(
        request,
        current_doctor,
        db,
        success=f"Cobro registrado correctamente para {patient.full_name}. Total: ${total_value:.2f}",
    )


@router.post("/charges/{charge_id}/status")
def update_charge_status(
    charge_id: int,
    request: Request,
    db: Session = Depends(get_db),
    payment_status: str = Form(...),
):
    current_doctor = get_logged_doctor(request, db)
    if not current_doctor:
        return _redirect_login()
    if not is_admin(current_doctor):
        return _redirect_app()

    charge = db.query(Charge).filter(Charge.id == charge_id).first()
    if not charge:
        return _render_finances(request, current_doctor, db, error="Cobro no encontrado.")

    payment_status = (payment_status or "").strip().lower()
    if payment_status not in {"pagado", "pendiente", "anulado"}:
        return _render_finances(request, current_doctor, db, error="Estado de pago inválido.")

    charge.payment_status = payment_status
    charge.updated_at = datetime.utcnow()
    db.commit()

    return _render_finances(request, current_doctor, db, success=f"Estado actualizado para el cobro #{charge.id}.")