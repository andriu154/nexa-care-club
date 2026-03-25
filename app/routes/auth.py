# app/routes/auth.py
from datetime import datetime

from fastapi import APIRouter, Depends, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import or_
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Doctor
from ..deps.passwords import hash_password, verify_password

router = APIRouter(tags=["Auth UI"])
templates = Jinja2Templates(directory="app/templates")


def get_logged_doctor(request: Request, db: Session) -> Doctor | None:
    doctor_id = request.session.get("doctor_id") if hasattr(request, "session") else None
    if not doctor_id:
        return None
    return db.query(Doctor).filter(Doctor.id == int(doctor_id)).first()


def is_admin(doctor: Doctor | None) -> bool:
    return bool(doctor and (doctor.role or "").strip().lower() == "admin")


@router.get("/login", response_class=HTMLResponse)
def login_form(request: Request):
    return templates.TemplateResponse(
        "login.html",
        {
            "request": request,
            "error": None,
            "current_doctor": None,
        },
    )


@router.post("/login")
def login_submit(
    request: Request,
    db: Session = Depends(get_db),
    registration: str = Form(...),
    password: str = Form(...),
):
    login_value = (registration or "").strip()
    pwd = (password or "").strip()

    if not login_value or not pwd:
        return templates.TemplateResponse(
            "login.html",
            {
                "request": request,
                "error": "Completa usuario o registro y contraseña.",
                "current_doctor": None,
            },
            status_code=400,
        )

    doctor = (
        db.query(Doctor)
        .filter(
            or_(
                Doctor.registration == login_value,
                Doctor.username == login_value,
            )
        )
        .first()
    )

    if not doctor or not doctor.password_hash:
        return templates.TemplateResponse(
            "login.html",
            {
                "request": request,
                "error": "Credenciales inválidas.",
                "current_doctor": None,
            },
            status_code=400,
        )

    if not getattr(doctor, "is_active", True):
        return templates.TemplateResponse(
            "login.html",
            {
                "request": request,
                "error": "Tu usuario está inactivo. Contacta al administrador.",
                "current_doctor": None,
            },
            status_code=403,
        )

    try:
        ok = verify_password(pwd, doctor.password_hash)
    except Exception:
        ok = False

    if not ok:
        return templates.TemplateResponse(
            "login.html",
            {
                "request": request,
                "error": "Credenciales inválidas.",
                "current_doctor": None,
            },
            status_code=400,
        )

    doctor.last_login_at = datetime.utcnow()
    db.commit()

    request.session["doctor_id"] = doctor.id
    request.session["login_at"] = datetime.utcnow().isoformat()

    if getattr(doctor, "must_change_password", False):
        return RedirectResponse(url="/change-password", status_code=302)

    return RedirectResponse(url="/app", status_code=302)


@router.get("/change-password", response_class=HTMLResponse)
def change_password_form(request: Request, db: Session = Depends(get_db)):
    current_doctor = get_logged_doctor(request, db)
    if not current_doctor:
        return RedirectResponse(url="/login", status_code=302)

    return templates.TemplateResponse(
        "change_password.html",
        {
            "request": request,
            "current_doctor": current_doctor,
            "error": None,
            "success": None,
            "force_mode": bool(getattr(current_doctor, "must_change_password", False)),
        },
    )


@router.post("/change-password")
def change_password_submit(
    request: Request,
    db: Session = Depends(get_db),
    current_password: str = Form(...),
    new_password: str = Form(...),
    confirm_password: str = Form(...),
):
    current_doctor = get_logged_doctor(request, db)
    if not current_doctor:
        return RedirectResponse(url="/login", status_code=302)

    current_password = (current_password or "").strip()
    new_password = (new_password or "").strip()
    confirm_password = (confirm_password or "").strip()

    if not verify_password(current_password, current_doctor.password_hash or ""):
        return templates.TemplateResponse(
            "change_password.html",
            {
                "request": request,
                "current_doctor": current_doctor,
                "error": "La contraseña actual no es correcta.",
                "success": None,
                "force_mode": bool(getattr(current_doctor, "must_change_password", False)),
            },
            status_code=400,
        )

    if len(new_password) < 8:
        return templates.TemplateResponse(
            "change_password.html",
            {
                "request": request,
                "current_doctor": current_doctor,
                "error": "La nueva contraseña debe tener al menos 8 caracteres.",
                "success": None,
                "force_mode": bool(getattr(current_doctor, "must_change_password", False)),
            },
            status_code=400,
        )

    if new_password != confirm_password:
        return templates.TemplateResponse(
            "change_password.html",
            {
                "request": request,
                "current_doctor": current_doctor,
                "error": "La confirmación no coincide.",
                "success": None,
                "force_mode": bool(getattr(current_doctor, "must_change_password", False)),
            },
            status_code=400,
        )

    if verify_password(new_password, current_doctor.password_hash or ""):
        return templates.TemplateResponse(
            "change_password.html",
            {
                "request": request,
                "current_doctor": current_doctor,
                "error": "La nueva contraseña debe ser diferente a la actual.",
                "success": None,
                "force_mode": bool(getattr(current_doctor, "must_change_password", False)),
            },
            status_code=400,
        )

    current_doctor.password_hash = hash_password(new_password)
    current_doctor.must_change_password = False
    current_doctor.updated_at = datetime.utcnow()
    db.commit()

    return templates.TemplateResponse(
        "change_password.html",
        {
            "request": request,
            "current_doctor": current_doctor,
            "error": None,
            "success": "Contraseña actualizada correctamente.",
            "force_mode": False,
        },
    )


@router.post("/logout")
def logout(request: Request):
    if hasattr(request, "session"):
        request.session.clear()
    return RedirectResponse(url="/login", status_code=302)