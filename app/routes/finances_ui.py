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
from ..models import (
    Charge,
    Doctor,
    Encounter,
    InventoryItem,
    InventoryMovement,
    Patient,
    ServiceCatalog,
    ServiceSupply,
)
from .auth import get_logged_doctor, is_admin

router = APIRouter(prefix="/app", tags=["Finances UI"])
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


def _allowed_units():
    return ["unidad", "ml", "vial", "ampolla", "caja", "jeringa", "par"]


def _allowed_movement_types():
    return {"purchase", "manual_in", "manual_out", "procedure_use", "correction"}


def _build_inventory_cost_for_service(service: ServiceCatalog | None) -> float:
    if not service:
        return 0.0

    total = 0.0
    for link in service.supply_links or []:
        item = link.item
        if not item:
            continue
        qty = _to_float(link.quantity)
        unit_cost = _to_float(item.average_cost)
        total += round(qty * unit_cost, 2)
    return round(total, 2)


def _consume_inventory_for_charge(
    db: Session,
    *,
    charge: Charge,
    service: ServiceCatalog | None,
    actor_doctor: Doctor | None,
):
    if not service:
        return {"used_items": [], "estimated_cost": 0.0, "warnings": []}

    used_items = []
    warnings = []
    estimated_cost = 0.0

    for link in service.supply_links or []:
        item = link.item
        if not item:
            continue

        qty = _to_float(link.quantity)
        if qty <= 0:
            continue

        current_stock = _to_float(item.current_stock)
        unit_cost = _to_float(item.average_cost)
        total_cost = round(qty * unit_cost, 2)

        estimated_cost += total_cost
        new_stock = round(current_stock - qty, 2)
        item.current_stock = new_stock
        item.updated_at = datetime.utcnow()

        movement = InventoryMovement(
            item_id=item.id,
            charge_id=charge.id,
            actor_doctor_id=actor_doctor.id if actor_doctor else None,
            movement_type="procedure_use",
            quantity=qty,
            unit_cost=unit_cost,
            total_cost=total_cost,
            reference=service.name,
            notes=f"Consumo automático por cobro #{charge.id}",
            created_at=datetime.utcnow(),
        )
        db.add(movement)

        used_items.append({
            "name": item.name,
            "quantity": qty,
            "unit": item.unit or "unidad",
        })

        min_stock = _to_float(item.minimum_stock)
        reorder_point = _to_float(item.reorder_point)
        threshold = max(min_stock, reorder_point)

        if new_stock < 0:
            warnings.append(f"{item.name} quedó con stock negativo ({new_stock:.2f}).")
        elif threshold > 0 and new_stock <= threshold:
            warnings.append(f"{item.name} quedó en stock bajo ({new_stock:.2f}).")

    return {
        "used_items": used_items,
        "estimated_cost": round(estimated_cost, 2),
        "warnings": warnings,
    }


def _common_admin_payload(request: Request, db: Session):
    services = (
        db.query(ServiceCatalog)
        .options(joinedload(ServiceCatalog.supply_links).joinedload(ServiceSupply.item))
        .order_by(ServiceCatalog.is_active.desc(), ServiceCatalog.name.asc())
        .all()
    )

    doctors = db.query(Doctor).filter(Doctor.is_active == True).order_by(Doctor.name.asc()).all()
    patients = db.query(Patient).order_by(Patient.full_name.asc()).all()

    inventory_items = (
        db.query(InventoryItem)
        .order_by(InventoryItem.is_active.desc(), InventoryItem.name.asc())
        .all()
    )

    inventory_movements = (
        db.query(InventoryMovement)
        .options(
            joinedload(InventoryMovement.item),
            joinedload(InventoryMovement.charge),
            joinedload(InventoryMovement.actor_doctor),
        )
        .order_by(InventoryMovement.created_at.desc(), InventoryMovement.id.desc())
        .limit(20)
        .all()
    )

    low_stock_items = []
    for item in inventory_items:
        current_stock = _to_float(item.current_stock)
        threshold = max(_to_float(item.minimum_stock), _to_float(item.reorder_point))
        item.is_low_stock = threshold > 0 and current_stock <= threshold
        if item.is_low_stock:
            low_stock_items.append(item)

    return {
        "services": services,
        "doctors": doctors,
        "patients": patients,
        "inventory_items": inventory_items,
        "inventory_movements": inventory_movements,
        "low_stock_items": low_stock_items,
    }


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
    common = _common_admin_payload(request, db)
    services = common["services"]

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
        stats = service_ranking.setdefault(
            service_name,
            {"income": 0.0, "expense": 0.0, "profit": 0.0, "count": 0},
        )
        stats["income"] += _to_float(c.total)
        stats["expense"] += _to_float(c.expense_amount)
        stats["profit"] += round(_to_float(c.total) - _to_float(c.expense_amount), 2)
        stats["count"] += 1

    ranking_doctors = sorted(doctor_ranking.items(), key=lambda x: x[1], reverse=True)
    ranking_services = sorted(service_ranking.items(), key=lambda x: x[1]["profit"], reverse=True)

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
            "recent_charges": month_charges[:30],
            "ranking_doctors": ranking_doctors,
            "ranking_services": ranking_services,
            "patients": common["patients"],
            "doctors": common["doctors"],
            "services": services,
            "form_defaults": form_defaults,
            "selected_patient": selected_patient,
            "selected_encounter": selected_encounter,
        },
    )


def _render_inventory(
    request: Request,
    current_doctor: Doctor,
    db: Session,
    error: str | None = None,
    success: str | None = None,
):
    if not is_admin(current_doctor):
        return _redirect_app()

    common = _common_admin_payload(request, db)

    return templates.TemplateResponse(
        "inventory.html",
        {
            "request": request,
            "current_doctor": current_doctor,
            "error": error,
            "success": success,
            "services": common["services"],
            "inventory_items": common["inventory_items"],
            "inventory_movements": common["inventory_movements"],
            "low_stock_items": common["low_stock_items"],
            "allowed_units": _allowed_units(),
            "summary": {
                "inventory_total_items": len(common["inventory_items"]),
                "inventory_low_stock_count": len(common["low_stock_items"]),
                "inventory_total_stock_value": round(
                    sum(_to_float(x.current_stock) * _to_float(x.average_cost) for x in common["inventory_items"]), 2
                ),
                "active_services": sum(1 for s in common["services"] if s.is_active),
            },
        },
    )


@router.get("/finances", response_class=HTMLResponse)
@router.get("/finances/", response_class=HTMLResponse)
def finances_page(request: Request, db: Session = Depends(get_db)):
    current_doctor = get_logged_doctor(request, db)
    if not current_doctor:
        return _redirect_login()
    return _render_finances(request, current_doctor, db)


@router.get("/inventory", response_class=HTMLResponse)
@router.get("/inventory/", response_class=HTMLResponse)
def inventory_page(request: Request, db: Session = Depends(get_db)):
    current_doctor = get_logged_doctor(request, db)
    if not current_doctor:
        return _redirect_login()
    return _render_inventory(request, current_doctor, db)


@router.post("/finances/services/create")
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


@router.post("/finances/services/{service_id}/update")
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
        return _render_inventory(request, current_doctor, db, error="Servicio no encontrado.")

    name = (name or "").strip()
    category = (category or "Consulta").strip()
    price = _parse_money(base_price)
    cost = _parse_money(base_cost)
    active = bool(is_active)

    if not name:
        return _render_inventory(request, current_doctor, db, error="El nombre del servicio es obligatorio.")
    if price < 0:
        return _render_inventory(request, current_doctor, db, error="El precio no puede ser negativo.")
    if cost < 0:
        return _render_inventory(request, current_doctor, db, error="El costo base no puede ser negativo.")

    duplicate = (
        db.query(ServiceCatalog)
        .filter(ServiceCatalog.id != service_id)
        .filter(ServiceCatalog.name == name)
        .first()
    )
    if duplicate:
        return _render_inventory(request, current_doctor, db, error="Ya existe otro servicio con ese nombre.")

    service.name = name
    service.category = category
    service.base_price = price
    service.base_cost = cost
    service.is_active = active
    service.updated_at = datetime.utcnow()
    db.commit()

    return _render_inventory(request, current_doctor, db, success=f"Servicio actualizado: {name}")


@router.post("/finances/services/{service_id}/delete")
def delete_service(service_id: int, request: Request, db: Session = Depends(get_db)):
    current_doctor = get_logged_doctor(request, db)
    if not current_doctor:
        return _redirect_login()
    if not is_admin(current_doctor):
        return _redirect_app()

    service = db.query(ServiceCatalog).filter(ServiceCatalog.id == service_id).first()
    if not service:
        return _render_inventory(request, current_doctor, db, error="Servicio no encontrado.")

    linked_charges = db.query(Charge).filter(Charge.service_id == service_id).count()
    if linked_charges > 0:
        return _render_inventory(
            request,
            current_doctor,
            db,
            error="No se puede eliminar ese servicio porque ya tiene cobros asociados. Puedes dejarlo inactivo.",
        )

    name = service.name
    db.delete(service)
    db.commit()

    return _render_inventory(request, current_doctor, db, success=f"Servicio eliminado: {name}")


@router.post("/inventory/create")
def create_inventory_item(
    request: Request,
    db: Session = Depends(get_db),
    name: str = Form(...),
    category: str = Form(""),
    presentation: str = Form(""),
    unit: str = Form("unidad"),
    current_stock: str = Form("0"),
    minimum_stock: str = Form("0"),
    reorder_point: str = Form("0"),
    average_cost: str = Form("0"),
    supplier: str = Form(""),
    notes: str = Form(""),
):
    current_doctor = get_logged_doctor(request, db)
    if not current_doctor:
        return _redirect_login()
    if not is_admin(current_doctor):
        return _redirect_app()

    name = (name or "").strip()
    category = (category or "").strip()
    presentation = (presentation or "").strip()
    supplier = (supplier or "").strip()
    notes = (notes or "").strip()
    unit = (unit or "unidad").strip().lower()

    stock = _parse_money(current_stock)
    minimum = _parse_money(minimum_stock)
    reorder = _parse_money(reorder_point)
    avg_cost = _parse_money(average_cost)

    if not name:
        return _render_inventory(request, current_doctor, db, error="El nombre del insumo es obligatorio.")
    if unit not in _allowed_units():
        unit = "unidad"
    if stock < 0 or minimum < 0 or reorder < 0 or avg_cost < 0:
        return _render_inventory(request, current_doctor, db, error="Los valores del inventario no pueden ser negativos.")

    existing = db.query(InventoryItem).filter(InventoryItem.name == name).first()
    if existing:
        existing.category = category or None
        existing.presentation = presentation or None
        existing.unit = unit
        existing.current_stock = stock
        existing.minimum_stock = minimum
        existing.reorder_point = reorder
        existing.average_cost = avg_cost
        existing.supplier = supplier or None
        existing.notes = notes or None
        existing.is_active = True
        existing.updated_at = datetime.utcnow()
        db.commit()
        return _render_inventory(request, current_doctor, db, success=f"Insumo actualizado: {name}")

    item = InventoryItem(
        name=name,
        category=category or None,
        presentation=presentation or None,
        unit=unit,
        current_stock=stock,
        minimum_stock=minimum,
        reorder_point=reorder,
        average_cost=avg_cost,
        supplier=supplier or None,
        notes=notes or None,
        is_active=True,
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
    )
    db.add(item)
    db.commit()

    return _render_inventory(request, current_doctor, db, success=f"Insumo creado: {name}")


@router.post("/inventory/{item_id}/update")
def update_inventory_item(
    item_id: int,
    request: Request,
    db: Session = Depends(get_db),
    name: str = Form(...),
    category: str = Form(""),
    presentation: str = Form(""),
    unit: str = Form("unidad"),
    current_stock: str = Form("0"),
    minimum_stock: str = Form("0"),
    reorder_point: str = Form("0"),
    average_cost: str = Form("0"),
    supplier: str = Form(""),
    notes: str = Form(""),
    is_active: str | None = Form(None),
):
    current_doctor = get_logged_doctor(request, db)
    if not current_doctor:
        return _redirect_login()
    if not is_admin(current_doctor):
        return _redirect_app()

    item = db.query(InventoryItem).filter(InventoryItem.id == item_id).first()
    if not item:
        return _render_inventory(request, current_doctor, db, error="Insumo no encontrado.")

    name = (name or "").strip()
    category = (category or "").strip()
    presentation = (presentation or "").strip()
    supplier = (supplier or "").strip()
    notes = (notes or "").strip()
    unit = (unit or "unidad").strip().lower()

    stock = _parse_money(current_stock)
    minimum = _parse_money(minimum_stock)
    reorder = _parse_money(reorder_point)
    avg_cost = _parse_money(average_cost)

    if not name:
        return _render_inventory(request, current_doctor, db, error="El nombre del insumo es obligatorio.")

    duplicate = (
        db.query(InventoryItem)
        .filter(InventoryItem.id != item_id)
        .filter(InventoryItem.name == name)
        .first()
    )
    if duplicate:
        return _render_inventory(request, current_doctor, db, error="Ya existe otro insumo con ese nombre.")

    if unit not in _allowed_units():
        unit = "unidad"

    if stock < 0 or minimum < 0 or reorder < 0 or avg_cost < 0:
        return _render_inventory(request, current_doctor, db, error="Los valores del inventario no pueden ser negativos.")

    item.name = name
    item.category = category or None
    item.presentation = presentation or None
    item.unit = unit
    item.current_stock = stock
    item.minimum_stock = minimum
    item.reorder_point = reorder
    item.average_cost = avg_cost
    item.supplier = supplier or None
    item.notes = notes or None
    item.is_active = bool(is_active)
    item.updated_at = datetime.utcnow()

    db.commit()

    return _render_inventory(request, current_doctor, db, success=f"Insumo actualizado: {name}")


@router.post("/inventory/{item_id}/movement")
def create_inventory_movement(
    item_id: int,
    request: Request,
    db: Session = Depends(get_db),
    movement_type: str = Form(...),
    quantity: str = Form(...),
    unit_cost: str = Form("0"),
    reference: str = Form(""),
    notes: str = Form(""),
):
    current_doctor = get_logged_doctor(request, db)
    if not current_doctor:
        return _redirect_login()
    if not is_admin(current_doctor):
        return _redirect_app()

    item = db.query(InventoryItem).filter(InventoryItem.id == item_id).first()
    if not item:
        return _render_inventory(request, current_doctor, db, error="Insumo no encontrado.")

    movement_type = (movement_type or "").strip().lower()
    qty = _parse_money(quantity)
    unit_cost_value = _parse_money(unit_cost)
    reference = (reference or "").strip()
    notes = (notes or "").strip()

    if movement_type not in _allowed_movement_types():
        return _render_inventory(request, current_doctor, db, error="Tipo de movimiento inválido.")
    if qty <= 0:
        return _render_inventory(request, current_doctor, db, error="La cantidad debe ser mayor a 0.")
    if unit_cost_value < 0:
        return _render_inventory(request, current_doctor, db, error="El costo unitario no puede ser negativo.")

    current_stock = _to_float(item.current_stock)

    if movement_type in {"purchase", "manual_in"}:
        new_stock = round(current_stock + qty, 2)
        if movement_type == "purchase" and qty > 0:
            previous_stock = current_stock
            previous_cost = _to_float(item.average_cost)
            weighted_total = (previous_stock * previous_cost) + (qty * unit_cost_value)
            item.average_cost = round(weighted_total / new_stock, 2) if new_stock > 0 else previous_cost
    elif movement_type in {"manual_out", "correction"}:
        new_stock = round(current_stock - qty, 2)
    else:
        new_stock = current_stock

    item.current_stock = new_stock
    item.updated_at = datetime.utcnow()

    if unit_cost_value == 0:
        unit_cost_value = _to_float(item.average_cost)

    total_cost = round(qty * unit_cost_value, 2)

    movement = InventoryMovement(
        item_id=item.id,
        actor_doctor_id=current_doctor.id,
        movement_type=movement_type,
        quantity=qty,
        unit_cost=unit_cost_value,
        total_cost=total_cost,
        reference=reference or None,
        notes=notes or None,
        created_at=datetime.utcnow(),
    )
    db.add(movement)
    db.commit()

    msg = f"Movimiento registrado en {item.name}. Stock actual: {new_stock:.2f}"
    if new_stock < 0:
        msg += " · Atención: el stock quedó negativo."

    return _render_inventory(request, current_doctor, db, success=msg)


@router.post("/finances/services/{service_id}/supplies/add")
def add_service_supply(
    service_id: int,
    request: Request,
    db: Session = Depends(get_db),
    item_id: int = Form(...),
    quantity: str = Form(...),
    is_optional: str | None = Form(None),
    notes: str = Form(""),
):
    current_doctor = get_logged_doctor(request, db)
    if not current_doctor:
        return _redirect_login()
    if not is_admin(current_doctor):
        return _redirect_app()

    service = (
        db.query(ServiceCatalog)
        .options(joinedload(ServiceCatalog.supply_links))
        .filter(ServiceCatalog.id == service_id)
        .first()
    )
    if not service:
        return _render_inventory(request, current_doctor, db, error="Servicio no encontrado.")

    item = db.query(InventoryItem).filter(InventoryItem.id == item_id).first()
    if not item:
        return _render_inventory(request, current_doctor, db, error="Insumo no encontrado.")

    qty = _parse_money(quantity)
    notes = (notes or "").strip()

    if qty <= 0:
        return _render_inventory(request, current_doctor, db, error="La cantidad del insumo debe ser mayor a 0.")

    existing = (
        db.query(ServiceSupply)
        .filter(ServiceSupply.service_id == service.id)
        .filter(ServiceSupply.item_id == item.id)
        .first()
    )
    if existing:
        existing.quantity = qty
        existing.is_optional = bool(is_optional)
        existing.notes = notes or None
        existing.updated_at = datetime.utcnow()
    else:
        link = ServiceSupply(
            service_id=service.id,
            item_id=item.id,
            quantity=qty,
            is_optional=bool(is_optional),
            notes=notes or None,
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
        )
        db.add(link)

    db.flush()
    service = (
        db.query(ServiceCatalog)
        .options(joinedload(ServiceCatalog.supply_links).joinedload(ServiceSupply.item))
        .filter(ServiceCatalog.id == service.id)
        .first()
    )

    calculated_cost = _build_inventory_cost_for_service(service)
    service.base_cost = calculated_cost
    service.updated_at = datetime.utcnow()

    db.commit()
    return _render_inventory(
        request,
        current_doctor,
        db,
        success=f"Insumo vinculado a {service.name}. Costo estimado recalculado: ${calculated_cost:.2f}",
    )


@router.post("/finances/services/{service_id}/supplies/{link_id}/delete")
def delete_service_supply(
    service_id: int,
    link_id: int,
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
        return _render_inventory(request, current_doctor, db, error="Servicio no encontrado.")

    link = (
        db.query(ServiceSupply)
        .filter(ServiceSupply.id == link_id)
        .filter(ServiceSupply.service_id == service_id)
        .first()
    )
    if not link:
        return _render_inventory(request, current_doctor, db, error="Vínculo de insumo no encontrado.")

    db.delete(link)
    db.flush()

    service = (
        db.query(ServiceCatalog)
        .options(joinedload(ServiceCatalog.supply_links).joinedload(ServiceSupply.item))
        .filter(ServiceCatalog.id == service_id)
        .first()
    )

    calculated_cost = _build_inventory_cost_for_service(service)
    service.base_cost = calculated_cost
    service.updated_at = datetime.utcnow()

    db.commit()
    return _render_inventory(
        request,
        current_doctor,
        db,
        success=f"Insumo desvinculado de {service.name}. Nuevo costo estimado: ${calculated_cost:.2f}",
    )


@router.post("/finances/charges/create")
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
    service = (
        db.query(ServiceCatalog)
        .options(joinedload(ServiceCatalog.supply_links).joinedload(ServiceSupply.item))
        .filter(ServiceCatalog.id == parsed_service_id)
        .first()
        if parsed_service_id else None
    )
    encounter = db.query(Encounter).filter(Encounter.id == parsed_encounter_id).first() if parsed_encounter_id else None

    subtotal_value = _parse_money(subtotal)
    discount_value = _parse_money(discount)
    expense_value = _parse_money(expense_amount)

    if subtotal_value <= 0 and service:
        subtotal_value = _to_float(service.base_price)

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
    db.flush()

    inventory_result = {"used_items": [], "estimated_cost": 0.0, "warnings": []}
    if service and payment_status != "anulado":
        inventory_result = _consume_inventory_for_charge(
            db,
            charge=charge,
            service=service,
            actor_doctor=current_doctor,
        )

    if expense_value <= 0 and inventory_result["estimated_cost"] > 0:
        charge.expense_amount = inventory_result["estimated_cost"]
        expense_value = inventory_result["estimated_cost"]
    elif expense_value <= 0 and service:
        charge.expense_amount = _to_float(service.base_cost)
        expense_value = _to_float(service.base_cost)

    db.commit()

    net_profit = round(total_value - expense_value, 2)

    msg = (
        f"Cobro registrado correctamente para {patient.full_name}. "
        f"Ingreso: ${total_value:.2f} · Egreso: ${expense_value:.2f} · Ganancia: ${net_profit:.2f}"
    )

    if inventory_result["used_items"]:
        resumen = ", ".join(
            f"{x['name']} ({x['quantity']:.2f} {x['unit']})"
            for x in inventory_result["used_items"][:4]
        )
        msg += f" · Inventario descontado: {resumen}"

    if inventory_result["warnings"]:
        msg += " · " + " ".join(inventory_result["warnings"])

    return _render_finances(request, current_doctor, db, success=msg)


@router.post("/finances/charges/{charge_id}/status")
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