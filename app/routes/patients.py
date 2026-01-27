from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from typing import List, Optional
import uuid
import os
import qrcode

from ..database import get_db
from ..models import Patient, Doctor
from ..deps.auth import get_current_doctor

router = APIRouter(prefix="/patients", tags=["Patients"])

# ✅ aseguramos carpeta qrs
QR_FOLDER = "qrs"
os.makedirs(QR_FOLDER, exist_ok=True)


# -----------------------------
# Schemas
# -----------------------------
class PatientCreate(BaseModel):
    full_name: str = Field(min_length=1, max_length=150)

class PatientOut(BaseModel):
    id: int
    full_name: str
    qr_code: str

    class Config:
        from_attributes = True

class BulkPatientsRequest(BaseModel):
    names: List[str]


# -----------------------------
# Helpers
# -----------------------------
def _generate_qr(qr_id: str) -> str:
    """
    Genera un QR PNG en /qrs y devuelve la ruta.
    """
    img = qrcode.make(qr_id)
    path = os.path.join(QR_FOLDER, f"{qr_id}.png")
    img.save(path)
    return path


# -----------------------------
# Endpoints (PROTEGIDOS con JWT)
# -----------------------------

@router.get("", response_model=List[PatientOut])
def list_patients(
    search: Optional[str] = None,
    db: Session = Depends(get_db),
    current_doctor: Doctor = Depends(get_current_doctor),
):
    """
    Lista pacientes.
    - ?search= filtra por nombre (full_name).
    """
    q = db.query(Patient)
    if search:
        s = f"%{search.strip()}%"
        q = q.filter(Patient.full_name.ilike(s))

    return q.order_by(Patient.id.desc()).all()


@router.get("/{patient_id}", response_model=PatientOut)
def get_patient(
    patient_id: int,
    db: Session = Depends(get_db),
    current_doctor: Doctor = Depends(get_current_doctor),
):
    patient = db.query(Patient).filter(Patient.id == patient_id).first()
    if not patient:
        raise HTTPException(status_code=404, detail="Paciente no encontrado")
    return patient


@router.post("", response_model=PatientOut, status_code=201)
def create_patient(
    payload: PatientCreate,
    db: Session = Depends(get_db),
    current_doctor: Doctor = Depends(get_current_doctor),
):
    """
    Crea 1 paciente con QR.
    - Evita duplicados exactos por full_name (puedes ajustar si quieres).
    """
    name = payload.full_name.strip()

    existing = db.query(Patient).filter(Patien
