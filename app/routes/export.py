from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
import pandas as pd

from ..database import get_db
from ..models import Patient, Attendance

router = APIRouter(prefix="/export", tags=["Export"])

@router.get("/excel")
def export_excel(db: Session = Depends(get_db)):
    # 📄 hoja 1: pacientes
    patients = db.query(Patient).all()
    patients_data = []

    for p in patients:
        patients_data.append({
            "Paciente": p.full_name,
            "Sesiones Completadas": p.completed_sessions,
            "Total Sesiones": p.total_sessions,
            "Estado": p.status
        })

    df_patients = pd.DataFrame(patients_data)

    # 📄 hoja 2: historial de asistencias
    attendance = db.query(Attendance).all()
    attendance_data = []

    for a in attendance:
        attendance_data.append({
            "Paciente ID": a.patient_id,
            "Doctor ID": a.doctor_id,
            "Sesión": a.session_number,
            "Fecha": a.timestamp
        })

    df_attendance = pd.DataFrame(attendance_data)

    # 📁 crear excel
    file_name = "nexa_care_club.xlsx"
    with pd.ExcelWriter(file_name, engine="openpyxl") as writer:
        df_patients.to_excel(writer, sheet_name="Pacientes", index=False)
        df_attendance.to_excel(writer, sheet_name="Asistencias", index=False)

    return {
        "message": "Excel generado correctamente ✅",
        "file": file_name
    }
