from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session
from typing import List
import uuid
import os
import qrcode

from ..database import get_db
from ..models import Patient

router = APIRouter(prefix="/patients", tags=["Patients"])

# ✅ aseguramos carpeta qrs
QR_FOLDER = "qrs"
os.makedirs(QR_FOLDER, exist_ok=True)

class BulkPatientsRequest(BaseModel):
    names: List[str]

@router.post("/bulk")
def create_patients_bulk(data: BulkPatientsRequest, db: Session = Depends(get_db)):
    created = []

    for name in data.names:
        qr_id = str(uuid.uuid4())

        # generar QR PNG
        img = qrcode.make(qr_id)
        img.save(os.path.join(QR_FOLDER, f"{qr_id}.png"))

        # guardar paciente en DB
        patient = Patient(full_name=name, qr_code=qr_id)
        db.add(patient)

        created.append({
            "full_name": name,
            "qr_code": qr_id,
            "qr_png": f"{QR_FOLDER}/{qr_id}.png"
        })

    db.commit()
    return {"created": created}
