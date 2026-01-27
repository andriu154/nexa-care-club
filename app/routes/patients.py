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

QR_FOLDER = "qrs"
os.makedirs(QR_FOLDER, exist_ok=True)

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

def generate_qr_png(qr_id: str) -> str:
    img = qrcode.make(qr_id)
    path = os.path.join(QR_FOLDER, f"{qr_id}.png")
    img.save(path)
    return path

@router.get("", response_model=List[PatientOut])
def list_patients(
    search: Optional[str] = None,
    db: Session = Depends(get_db),
    current_doctor: Doctor = Depends(get_current_doctor),
):
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
    name = payload.full_name.strip()

    existing = db.query(Patient).filter(Patient.full_name == name).first()
    if existing:
        return existing

    qr_id = str(uuid.uuid4())
    generate_qr_png(qr_id)

    patient = Patient(full_name=name, qr_code=qr_id)
    db.add(patient)
    db.commit()
    db.refresh(patient)
    return patient

@router.post("/bulk")
def create_patients_bulk(
    data: BulkPatientsRequest,
    db: Session = Depends(get_db),
    current_doctor: Doctor = Depends(get_current_doctor),
):
    created = []

    for name in data.names:
        clean_name = name.strip()
        if not clean_name:
            continue

        existing = db.query(Patient).filter(Patient.full_name == clean_name).first()
        if existing:
            created.append({
                "id": existing.id,
                "full_name": existing.full_name,
                "qr_code": existing.qr_code,
                "qr_png": f"{QR_FOLDER}/{existing.qr_code}.png"
            })
            continue

        qr_id = str(uuid.uuid4())
        generate_qr_png(qr_id)

        patient = Patient(full_name=clean_name, qr_code=qr_id)
        db.add(patient)

        created.append({
            "full_name": clean_name,
            "qr_code": qr_id,
            "qr_png": f"{QR_FOLDER}/{qr_id}.png"
        })

    db.commit()
    return {"created": created}
