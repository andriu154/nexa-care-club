from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Doctor
from ..security.jwt import decode_token

bearer_scheme = HTTPBearer(auto_error=False)

# =========================
# JWT (API) — NO SE TOCA
# =========================
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
# UI (Sesión por cookie)
# =========================
def get_logged_doctor(
    request: Request,
    db: Session,
) -> Doctor | None:
    """
    Devuelve Doctor si hay sesión válida; si no, None.
    """
    doctor_id = request.session.get("doctor_id")
    if not doctor_id:
        return None

    doctor = db.query(Doctor).filter(Doctor.id == doctor_id).first()
    if not doctor:
        request.session.clear()
        return None

    return doctor
