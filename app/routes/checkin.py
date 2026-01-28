from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from datetime import datetime

from ..database import get_db
from ..deps.auth import get_current_doctor
from ..models import Patient, Attendance, Doctor

router = APIRouter(prefix="/checkin", tags=["Check-in"])


@router.post("/{qr_code}")
def check_in_patient(qr_code: str, db: Session = Depends(get_db), current_doctor: Doctor = Depends(get_current_doctor)):
    # 1) buscar paciente por QR
    patient = db.query(Patient).filter(Patient.qr_code == qr_code).first()
    if not patient:
        raise HTTPException(status_code=404, detail="Paciente no encontrado")

    # 2) validar sesiones
    if patient.completed_sessions >= patient.total_sessions:
        return {
            "message": "Protocolo ya completado",
            "patient": patient.full_name,
            "status": patient.status
        }

    # 3) aumentar sesión
    patient.completed_sessions += 1

    # 4) registrar asistencia
    attendance = Attendance(
        patient_id=patient.id,
        doctor_id=current_doctor.id,
        session_number=patient.completed_sessions,
        timestamp=datetime.utcnow()
    )
    db.add(attendance)

    # 5) actualizar estado
    if patient.completed_sessions == patient.total_sessions:
        patient.status = "Completado"

    db.commit()

    return {
        "patient": patient.full_name,
        "session": patient.completed_sessions,
        "total_sessions": patient.total_sessions,
        "status": patient.status,
        "message": "Check-in registrado ✅"
    }
