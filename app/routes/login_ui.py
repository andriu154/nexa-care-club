from fastapi import APIRouter, Depends, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from starlette.status import HTTP_303_SEE_OTHER

from ..database import get_db
from ..models import Doctor
from ..deps.passwords import verify_password

router = APIRouter(tags=["Login UI"])
templates = Jinja2Templates(directory="app/templates")


@router.get("/login", response_class=HTMLResponse)
def login_form(request: Request):
    return templates.TemplateResponse(
        "login.html",
        {
            "request": request,
            "error": None,
            "current_doctor": None,  # importante para base.html
        },
    )


@router.post("/login")
def login_post(
    request: Request,
    registration: str = Form(...),
    password: str = Form(...),
    db: Session = Depends(get_db),
):
    reg = (registration or "").strip()
    pwd = (password or "").strip()

    doctor = db.query(Doctor).filter(Doctor.registration == reg).first()

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

    if not verify_password(pwd, doctor.password_hash):
        return templates.TemplateResponse(
            "login.html",
            {
                "request": request,
                "error": "Credenciales inválidas.",
                "current_doctor": None,
            },
            status_code=400,
        )

    # ✅ crear sesión
    request.session["doctor_id"] = doctor.id

    return RedirectResponse(url="/app", status_code=HTTP_303_SEE_OTHER)


@router.post("/logout")
def logout(request: Request):
    request.session.clear()
    return RedirectResponse(url="/login", status_code=HTTP_303_SEE_OTHER)
