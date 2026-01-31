# =========================
# ✅ app/routes/auth.py
# (LOGIN/LOGOUT UI con sesiones)
# =========================
from datetime import datetime
from fastapi import APIRouter, Depends, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from passlib.context import CryptContext
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Doctor

router = APIRouter(tags=["Auth UI"])
templates = Jinja2Templates(directory="app/templates")

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def get_logged_doctor(request: Request, db: Session) -> Doctor | None:
    doctor_id = request.session.get("doctor_id") if hasattr(request, "session") else None
    if not doctor_id:
        return None
    return db.query(Doctor).filter(Doctor.id == int(doctor_id)).first()


@router.get("/login", response_class=HTMLResponse)
def login_form(request: Request):
    return templates.TemplateResponse("login.html", {"request": request, "error": None})


@router.post("/login")
def login_submit(
    request: Request,
    db: Session = Depends(get_db),
    registration: str = Form(...),
    password: str = Form(...),
):
    reg = (registration or "").strip()
    pwd = (password or "").strip()

    doctor = db.query(Doctor).filter(Doctor.registration == reg).first()
    if not doctor or not doctor.password_hash:
        return templates.TemplateResponse(
            "login.html",
            {"request": request, "error": "Credenciales inválidas."},
            status_code=400,
        )

    if not pwd_context.verify(pwd, doctor.password_hash):
        return templates.TemplateResponse(
            "login.html",
            {"request": request, "error": "Credenciales inválidas."},
            status_code=400,
        )

    request.session["doctor_id"] = doctor.id
    request.session["login_at"] = datetime.utcnow().isoformat()

    return RedirectResponse(url="/app", status_code=302)


@router.post("/logout")
def logout(request: Request):
    if hasattr(request, "session"):
        request.session.clear()
    return RedirectResponse(url="/login", status_code=302)
