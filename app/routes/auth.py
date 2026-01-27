from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Doctor
from ..security.jwt import create_access_token

router = APIRouter(prefix="/auth", tags=["Auth"])

class LoginRequest(BaseModel):
    doctor_id: int
    pin: str

@router.post("/login")
def login(data: LoginRequest, db: Session = Depends(get_db)):
    doctor = db.query(Doctor).filter(Doctor.id == data.doctor_id).first()
    if not doctor:
        raise HTTPException(status_code=404, detail="Doctor no encontrado")

    if doctor.pin != data.pin:
        raise HTTPException(status_code=401, detail="PIN incorrecto")

    token = create_access_token(doctor_id=doctor.id, doctor_name=doctor.name)

    return {
        "access_token": token,
        "token_type": "bearer",
        "doctor_id": doctor.id,
        "doctor": doctor.name,
        "message": "Login exitoso ✅",
    }
