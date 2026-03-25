# app/routes/professionals_ui.py
from datetime import datetime

from fastapi import APIRouter, Depends, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
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
    return (value or "").strip().lower().replace(" ", "")


def _render_professionals(
    request: Request,
    current_doctor: Doctor,
    db: Session,
    error: str | None = None,
    success: str | None = None,
    form_data: dict | None = None,
    status_code: int = 200,
):
    professionals = db.query(Doctor).order_by(Doctor.is_active.desc(), Doctor.name.asc()).all()
    return templates.TemplateResponse(
        "professionals.html",
        {
            "request": request,
            "current_doctor": current_doctor,
            "professionals": professionals,
            "error": error,
            "success": success,
            "form_data": form_data or {},
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
    role = (role or "doctor").strip().lower()

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

    if len(temporary_password) < 8:
        return _render_professionals(
            request,
            current_doctor,
            db,
            error="La contraseña temporal debe tener al menos 8 caracteres.",
            form_data=form_data,
            status_code=400,
        )

    if role not in {"admin", "doctor"}:
        role = "doctor"

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
    target.updated_at = datetime.utcnow()
    db.commit()

    return _render_professionals(
        request,
        current_doctor,
        db,
        success=f"Contraseña temporal restablecida para {target.name}. Deberá cambiarla al ingresar.",
    )