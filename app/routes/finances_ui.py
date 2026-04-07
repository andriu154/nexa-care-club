# app/routes/finances_ui.py
from datetime import datetime
import os
import re
import unicodedata
from difflib import SequenceMatcher
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


def _strip_accents(value: str) -> str:
    value = unicodedata.normalize("NFD", value or "")
    return "".join(ch for ch in value if unicodedata.category(ch) != "Mn")


def _normalize_service_text(value: str) -> str:
    text = _strip_accents((value or "").strip().lower())
    text = re.sub(r"[^a-z0-9\s]", " ", text)
    tokens = [tok for tok in text.split() if tok]

    token_map = {
        "medico": "medic",
        "medica": "medic",
        "medicos": "medic",
        "medicas": "medic",
        "estetico": "estetic",
        "estetica": "estetic",
        "esteticos": "estetic",
        "esteticas": "estetic",
        "botulinica": "botulinic",
        "botulinico": "botulinic",
        "consulta": "consulta",
        "control": "control",
        "general": "general",
        "rinomodelacion": "rinomodelacion",
        "rinomodelacione": "rinomodelacion",
    }

    normalized_tokens = [token_map.get(tok, tok) for tok in tokens]
    return " ".join(normalized_tokens).strip()


def _canonical_service_label(raw_label: str, catalog_services: list[ServiceCatalog]) -> str:
    source = (raw_label or "").strip()
    if not source:
        return "Sin servicio"

    normalized_source = _normalize_service_text(source)
    if not normalized_source:
        return source

    best_label = source
    best_ratio = 0.0

    for item in catalog_services:
        catalog_name = (item.name or "").strip()
        if not catalog_name:
            continue

        normalized_catalog = _normalize_service_text(catalog_name)
        if not normalized_catalog:
            continue

        if normalized_catalog == normalized_source:
            return catalog_name

        ratio = SequenceMatcher(None, normalized_source, normalized_catalog).ratio()
        if ratio > best_ratio:
            best_ratio = ratio
            best_label = catalog_name

    if best_ratio >= 0.86:
        return best_label

    return source


def _charge_service_label(charge: Charge, catalog_services: list[ServiceCatalog]) -> str:
    if charge.service and charge.service.name:
        return charge.service.name.strip()

    if charge.description:
        return _canonical_service_label(charge.description, catalog_services)

    return "Sin servicio"


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

    services = db.query(ServiceCatalog).order_by(ServiceCatalog.is_active.desc(), ServiceCatalog.name.asc()).all()
    doctors = db.query(Doctor).filter(Doctor.is_active == True).order_by(Doctor.name.asc()).all()
    patients = db.query(Patient).order_by(Patient.full_name.asc()).all()

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

    for c in month_charges:
        c.display_service_label = _charge_service_label(c, services)
        c.display_expense_amount = _to_float(getattr(c, "expense_amount", 0))
        c.display_profit = round(_to_float(c.total) - c.display_expense_amount, 2)

    today_local = datetime.now(APP_TZ).date()

    paid_total = sum(_to_float(c.total) for c in month_charges if c.payment_status == "pagado")
    pending_total = sum(_to_float(c.total) for c in month_charges if c.payment_status == "pendiente")
    canceled_total = sum(_to_float(c.total) for c in month_charges if c.payment_status == "anulado")
    paid_expense_total = sum(_to_float(c.expense_amount) for c in month_charges if c.payment_status == "pagado")
    net_profit_total = round(paid_total - paid_expense_total, 2)

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

        doctor_name = c.doctor.name.strip() if c.doctor and c.doctor.name else "Sin profesional"
        doctor_ranking.setdefault(doctor_name, 0.0)
        doctor_ranking[doctor_name] += _to_float(c.total)

        service_name = c.display_service_label or "Sin servicio"
        service_stats = service_ranking.setdefault(
            service_name,
            {
                "income": 0.0,
                "expense": 0.0,
                "profit": 0.0,
                "count": 0,
            },
        )
        service_stats["income"] += _to_float(c.total)
        service_stats["expense"] += _to_float(c.expense_amount)
        service_stats["profit"] += round(_to_float(c.total) - _to_float(c.expense_amount), 2)
        service_stats["count"] += 1

    ranking_doctors = sorted(doctor_ranking.items(), key=lambda x: x[1], reverse=True)
    ranking_services = sorted(service_ranking.items(), key=lambda x: x[1]["profit"], reverse=True)

    recent_charges = month_charges[:30]

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
        "expense_amount": "0.00",
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
                "paid_expense_total": round(paid_expense_total, 2),
                "net_profit_total": round(net_profit_total, 2),
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
    base_cost: str = Form("0"),
):
    current_doctor = get_logged_doctor(request, db)
    if not current_doctor:
        return _redirect_login()
    if not is_admin(current_doctor):
        return _redirect_app()

    name = (name or "").strip()
    category = (category or "Consulta").strip()
    price = _parse_money(base_price)
    cost = _parse_money(base_cost)

    if not name:
        return _render_finances(request, current_doctor, db, error="El nombre del servicio es obligatorio.")

    if price < 0:
        return _render_finances(request, current_doctor, db, error="El precio no puede ser negativo.")

    if cost < 0:
        return _render_finances(request, current_doctor, db, error="El costo base no puede ser negativo.")

    existing = db.query(ServiceCatalog).filter(ServiceCatalog.name == name).first()
    if existing:
        existing.category = category or existing.category
        existing.base_price = price
        existing.base_cost = cost
        existing.is_active = True
        existing.updated_at = datetime.utcnow()
        db.commit()
        return _render_finances(request, current_doctor, db, success=f"Servicio actualizado: {name}")

    item = ServiceCatalog(
        name=name,
        category=category,
        base_price=price,
        base_cost=cost,
        is_active=True,
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
    )
    db.add(item)
    db.commit()

    return _render_finances(request, current_doctor, db, success=f"Servicio creado: {name}")


@router.post("/services/{service_id}/update")
def update_service(
    service_id: int,
    request: Request,
    db: Session = Depends(get_db),
    name: str = Form(...),
    category: str = Form("Consulta"),
    base_price: str = Form(...),
    base_cost: str = Form("0"),
    is_active: str | None = Form(None),
):
    current_doctor = get_logged_doctor(request, db)
    if not current_doctor:
        return _redirect_login()
    if not is_admin(current_doctor):
        return _redirect_app()

    service = db.query(ServiceCatalog).filter(ServiceCatalog.id == service_id).first()
    if not service:
        return _render_finances(request, current_doctor, db, error="Servicio no encontrado.")

    name = (name or "").strip()
    category = (category or "Consulta").strip()
    price = _parse_money(base_price)
    cost = _parse_money(base_cost)
    active = bool(is_active)

    if not name:
        return _render_finances(request, current_doctor, db, error="El nombre del servicio es obligatorio.")

    if price < 0:
        return _render_finances(request, current_doctor, db, error="El precio no puede ser negativo.")

    if cost < 0:
        return _render_finances(request, current_doctor, db, error="El costo base no puede ser negativo.")

    duplicate = (
        db.query(ServiceCatalog)
        .filter(ServiceCatalog.id != service_id)
        .filter(ServiceCatalog.name == name)
        .first()
    )
    if duplicate:
        return _render_finances(request, current_doctor, db, error="Ya existe otro servicio con ese nombre.")

    service.name = name
    service.category = category
    service.base_price = price
    service.base_cost = cost
    service.is_active = active
    service.updated_at = datetime.utcnow()
    db.commit()

    estado = "activo" if active else "inactivo"
    return _render_finances(request, current_doctor, db, success=f"Servicio actualizado: {name} ({estado}).")


@router.post("/services/{service_id}/delete")
def delete_service(
    service_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    current_doctor = get_logged_doctor(request, db)
    if not current_doctor:
        return _redirect_login()
    if not is_admin(current_doctor):
        return _redirect_app()

    service = db.query(ServiceCatalog).filter(ServiceCatalog.id == service_id).first()
    if not service:
        return _render_finances(request, current_doctor, db, error="Servicio no encontrado.")

    linked_charges = db.query(Charge).filter(Charge.service_id == service_id).count()
    if linked_charges > 0:
        return _render_finances(
            request,
            current_doctor,
            db,
            error="No se puede eliminar ese servicio porque ya tiene cobros asociados. Puedes dejarlo inactivo.",
        )

    name = service.name
    db.delete(service)
    db.commit()

    return _render_finances(request, current_doctor, db, success=f"Servicio eliminado: {name}")


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
    expense_amount: str = Form("0"),
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
    expense_value = _parse_money(expense_amount)

    if subtotal_value <= 0 and service:
        subtotal_value = _to_float(service.base_price)

    if expense_value <= 0 and service:
        expense_value = _to_float(service.base_cost)

    if subtotal_value <= 0:
        return _render_finances(request, current_doctor, db, error="El subtotal debe ser mayor a 0.")

    if discount_value < 0:
        return _render_finances(request, current_doctor, db, error="El descuento no puede ser negativo.")

    if expense_value < 0:
        return _render_finances(request, current_doctor, db, error="La inversión no puede ser negativa.")

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
        expense_amount=expense_value,
        payment_method=payment_method,
        payment_status=payment_status,
        charge_date=charge_dt,
        notes=(notes or "").strip() or None,
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
    )
    db.add(charge)
    db.commit()

    net_profit = round(total_value - expense_value, 2)

    return _render_finances(
        request,
        current_doctor,
        db,
        success=(
            f"Cobro registrado correctamente para {patient.full_name}. "
            f"Ingreso: ${total_value:.2f} · Egreso: ${expense_value:.2f} · Ganancia: ${net_profit:.2f}"
        ),
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