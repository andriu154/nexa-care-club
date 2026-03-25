# app/routes/professionals_ui.py
from datetime import datetime

from fastapi import APIRouter, Depends, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import or_
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Doctor
from ..deps.passwords import hash_password
from .auth import get_logged_doctor, is_admin

router = APIRouter(prefix="/app/professionals", tags=["Professionals UI"])
templates = Jinja2Templates(directory="app/templates")


def _redirect_login():
    return RedirectResponse(url="/login", status_code=302)


def _redirect_app():
    return RedirectResponse(url="/app", status_code=302)


def _normalize_username(value: str) -> str:
    value = (value or "").strip().lower()
    return "".join(ch for ch in value if ch.isalnum() or ch in {"_", ".", "-"})[:50]


def _normalize_role(value: str) -> str:
    value = (value or "doctor").strip().lower()
    return value if value in {"admin", "doctor"} else "doctor"


def _format_dt(dt_value):
    if not dt_value:
        return "—"
    try:
        return dt_value.strftime("%Y-%m-%d %H:%M")
    except Exception:
        return "—"


def _count_admins(db: Session) -> int:
    return db.query(Doctor).filter(Doctor.role == "admin", Doctor.is_active == True).count()


def _render_professionals(
    request: Request,
    current_doctor: Doctor,
    db: Session,
    error: str | None = None,
    success: str | None = None,
    form_data: dict | None = None,
    status_code: int = 200,
    editing_id: int | None = None,
):
    professionals = db.query(Doctor).order_by(Doctor.is_active.desc(), Doctor.name.asc()).all()

    for p in professionals:
        p.created_at_label = _format_dt(getattr(p, "created_at", None))
        p.updated_at_label = _format_dt(getattr(p, "updated_at", None))
        p.last_login_at_label = _format_dt(getattr(p, "last_login_at", None))
        p.is_self = bool(current_doctor and p.id == current_doctor.id)

    return templates.TemplateResponse(
        "professionals.html",
        {
            "request": request,
            "current_doctor": current_doctor,
            "professionals": professionals,
            "error": error,
            "success": success,
            "form_data": form_data or {},
            "editing_id": editing_id,
        },
        status_code=status_code,
    )


@router.get("", response_class=HTMLResponse)
@router.get("/", response_class=HTMLResponse)
def professionals_page(request: Request, db: Session = Depends(get_db)):
    current_doctor = get_logged_doctor(request, db)
    if not current_doctor:
        return _redirect_login()
    if not is_admin(current_doctor):
        return _redirect_app()

    return _render_professionals(request, current_doctor, db)


@router.post("/create")
def create_professional(
    request: Request,
    db: Session = Depends(get_db),
    name: str = Form(...),
    specialty: str = Form(""),
    registration: str = Form(...),
    username: str = Form(...),
    temporary_password: str = Form(...),
    role: str = Form("doctor"),
):
    current_doctor = get_logged_doctor(request, db)
    if not current_doctor:
        return _redirect_login()
    if not is_admin(current_doctor):
        return _redirect_app()

    name = (name or "").strip()
    specialty = (specialty or "").strip()
    registration = (registration or "").strip()
    username = _normalize_username(username)
    temporary_password = (temporary_password or "").strip()
    role = _normalize_role(role)

    form_data = {
        "name": name,
        "specialty": specialty,
        "registration": registration,
        "username": username,
        "role": role,
    }

    if not name or not registration or not username or not temporary_password:
        return _render_professionals(
            request,
            current_doctor,
            db,
            error="Completa todos los campos obligatorios.",
            form_data=form_data,
            status_code=400,
        )

    if len(username) < 3:
        return _render_professionals(
            request,
            current_doctor,
            db,
            error="El usuario debe tener al menos 3 caracteres.",
            form_data=form_data,
            status_code=400,
        )

    if len(temporary_password) < 8:
        return _render_professionals(
            request,
            current_doctor,
            db,
            error="La contraseña temporal debe tener al menos 8 caracteres.",
            form_data=form_data,
            status_code=400,
        )

    exists_reg = db.query(Doctor).filter(Doctor.registration == registration).first()
    if exists_reg:
        return _render_professionals(
            request,
            current_doctor,
            db,
            error="Ya existe un profesional con ese registro.",
            form_data=form_data,
            status_code=400,
        )

    exists_user = db.query(Doctor).filter(Doctor.username == username).first()
    if exists_user:
        return _render_professionals(
            request,
            current_doctor,
            db,
            error="Ese usuario ya existe.",
            form_data=form_data,
            status_code=400,
        )

    doctor = Doctor(
        name=name,
        specialty=specialty or None,
        registration=registration,
        username=username,
        password_hash=hash_password(temporary_password),
        pin="0000",
        role=role,
        is_active=True,
        must_change_password=True,
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
    )
    db.add(doctor)
    db.commit()

    return _render_professionals(
        request,
        current_doctor,
        db,
        success=f"Profesional creado correctamente. Usuario: {username}. Debe cambiar su contraseña al ingresar.",
    )


@router.post("/{doctor_id}/update")
def update_professional(
    doctor_id: int,
    request: Request,
    db: Session = Depends(get_db),
    name: str = Form(...),
    specialty: str = Form(""),
    registration: str = Form(...),
    username: str = Form(...),
    role: str = Form("doctor"),
):
    current_doctor = get_logged_doctor(request, db)
    if not current_doctor:
        return _redirect_login()
    if not is_admin(current_doctor):
        return _redirect_app()

    target = db.query(Doctor).filter(Doctor.id == doctor_id).first()
    if not target:
        return _render_professionals(
            request,
            current_doctor,
            db,
            error="Profesional no encontrado.",
            status_code=404,
        )

    name = (name or "").strip()
    specialty = (specialty or "").strip()
    registration = (registration or "").strip()
    username = _normalize_username(username)
    role = _normalize_role(role)

    form_data = {
        "name": name,
        "specialty": specialty,
        "registration": registration,
        "username": username,
        "role": role,
    }

    if not name or not registration or not username:
        return _render_professionals(
            request,
            current_doctor,
            db,
            error="Nombre, registro y usuario son obligatorios.",
            form_data=form_data,
            status_code=400,
            editing_id=doctor_id,
        )

    if len(username) < 3:
        return _render_professionals(
            request,
            current_doctor,
            db,
            error="El usuario debe tener al menos 3 caracteres.",
            form_data=form_data,
            status_code=400,
            editing_id=doctor_id,
        )

    exists_reg = (
        db.query(Doctor)
        .filter(Doctor.registration == registration, Doctor.id != doctor_id)
        .first()
    )
    if exists_reg:
        return _render_professionals(
            request,
            current_doctor,
            db,
            error="Ya existe otro profesional con ese registro.",
            form_data=form_data,
            status_code=400,
            editing_id=doctor_id,
        )

    exists_user = (
        db.query(Doctor)
        .filter(Doctor.username == username, Doctor.id != doctor_id)
        .first()
    )
    if exists_user:
        return _render_professionals(
            request,
            current_doctor,
            db,
            error="Ya existe otro profesional con ese usuario.",
            form_data=form_data,
            status_code=400,
            editing_id=doctor_id,
        )

    if target.id == current_doctor.id and role != "admin":
        return _render_professionals(
            request,
            current_doctor,
            db,
            error="No puedes quitarte tu propio rol de administrador desde esta sesión.",
            form_data=form_data,
            status_code=400,
            editing_id=doctor_id,
        )

    if target.role == "admin" and role != "admin" and _count_admins(db) <= 1:
        return _render_professionals(
            request,
            current_doctor,
            db,
            error="Debe existir al menos un administrador activo en el sistema.",
            form_data=form_data,
            status_code=400,
            editing_id=doctor_id,
        )

    target.name = name
    target.specialty = specialty or None
    target.registration = registration
    target.username = username
    target.role = role
    target.updated_at = datetime.utcnow()
    db.commit()

    return _render_professionals(
        request,
        current_doctor,
        db,
        success=f"Profesional actualizado: {target.name}",
    )


@router.post("/{doctor_id}/toggle-active")
def toggle_professional_active(
    doctor_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    current_doctor = get_logged_doctor(request, db)
    if not current_doctor:
        return _redirect_login()
    if not is_admin(current_doctor):
        return _redirect_app()

    target = db.query(Doctor).filter(Doctor.id == doctor_id).first()
    if not target:
        return _render_professionals(
            request,
            current_doctor,
            db,
            error="Profesional no encontrado.",
            status_code=404,
        )

    if target.id == current_doctor.id and target.is_active:
        return _render_professionals(
            request,
            current_doctor,
            db,
            error="No puedes desactivar tu propio usuario mientras estás conectado.",
            status_code=400,
        )

    if target.role == "admin" and target.is_active and _count_admins(db) <= 1:
        return _render_professionals(
            request,
            current_doctor,
            db,
            error="No puedes desactivar al último administrador activo del sistema.",
            status_code=400,
        )

    target.is_active = not bool(target.is_active)
    target.updated_at = datetime.utcnow()
    db.commit()

    estado = "activado" if target.is_active else "desactivado"
    return _render_professionals(
        request,
        current_doctor,
        db,
        success=f"Usuario {estado}: {target.name}",
    )


@router.post("/{doctor_id}/reset-password")
def reset_professional_password(
    doctor_id: int,
    request: Request,
    db: Session = Depends(get_db),
    temporary_password: str = Form(...),
):
    current_doctor = get_logged_doctor(request, db)
    if not current_doctor:
        return _redirect_login()
    if not is_admin(current_doctor):
        return _redirect_app()

    target = db.query(Doctor).filter(Doctor.id == doctor_id).first()
    if not target:
        return _render_professionals(
            request,
            current_doctor,
            db,
            error="Profesional no encontrado.",
            status_code=404,
        )

    temporary_password = (temporary_password or "").strip()
    if len(temporary_password) < 8:
        return _render_professionals(
            request,
            current_doctor,
            db,
            error="La nueva contraseña temporal debe tener al menos 8 caracteres.",
            status_code=400,
        )

    target.password_hash = hash_password(temporary_password)
    target.must_change_password = True
    target.is_active = True
    target.updated_at = datetime.utcnow()
    db.commit()

    return _render_professionals(
        request,
        current_doctor,
        db,
        success=f"Contraseña temporal restablecida para {target.name}. Deberá cambiarla al ingresar.",
    )