from fastapi import Depends, HTTPException, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from starlette.status import HTTP_303_SEE_OTHER

from ..database import get_db
from ..models import Doctor
from ..security.jwt import decode_token
from ..deps.passwords import verify_password

# =========================
# JWT (API) — NO SE TOCA
# =========================
bearer_scheme = HTTPBearer(auto_error=False)


def get_current_doctor(
    creds: HTTPAuthorizationCredentials = Depends(bearer_scheme),
    db: Session = Depends(get_db),
) -> Doctor:
    if creds is None or not creds.credentials:
        raise HTTPException(status_code=401, detail="Falta token (Authorization: Bearer)")

    token = creds.credentials
    try:
        payload = decode_token(token)
        doctor_id = int(payload.get("sub"))
    except Exception:
        raise HTTPException(status_code=401, detail="Token inválido o expirado")

    doctor = db.query(Doctor).filter(Doctor.id == doctor_id).first()
    if not doctor:
        raise HTTPException(status_code=401, detail="Doctor del token no existe")

    return doctor


# =========================
# UI LOGIN (SESIONES)
# =========================
templates = Jinja2Templates(directory="app/templates")


def get_current_doctor_ui(
    request: Request,
    db: Session = Depends(get_db),
) -> Doctor:
    doctor_id = request.session.get("doctor_id")
    if not doctor_id:
        raise HTTPException(status_code=401, detail="No autenticado")

    doctor = db.query(Doctor).filter(Doctor.id == doctor_id).first()
    if not doctor:
        request.session.clear()
        raise HTTPException(status_code=401, detail="Sesión inválida")

    return doctor


# ---------- LOGIN UI ----------
def router():
    pass
