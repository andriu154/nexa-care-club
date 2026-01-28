from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
import secrets

from ..database import get_db
from ..models import Patient

router = APIRouter(prefix="/patients", tags=["Patients"])


def _generate_qr_code(db: Session) -> str:
    """
    Genera un QR code corto y único en BD.
    Ejemplo: QR-8F3K2P9A
    """
    while True:
        code = "QR-" + secrets.token_hex(4).upper()  # 8 chars
        exists = db.query(Patient).filter(Patient.qr_code == code).first()
        if not exists:
            return code


@router.get("/")
def list_patients(db: Session = Depends(get_db)):
    patients = db.query(Patient).order_by(Patient.id.desc()).all()
    return [
        {
            "id": p.id,
            "full_name": p.full_name,
            "qr_code": p.qr_code,
            "total_sessions": p.total_sessions,
            "completed_sessions": p.completed_sessions,
            "status": p.status,
        }
        for p in patients
    ]


@router.get("/{patient_id}")
def get_patient(patient_id: int, db: Session = Depends(get_db)):
    p = db.query(Patient).filter(Patient.id == patient_id).first()
    if not p:
        raise HTTPException(status_code=404, detail="Paciente no encontrado")

    return {
        "id": p.id,
        "full_name": p.full_name,
        "qr_code": p.qr_code,
        "total_sessions": p.total_sessions,
        "completed_sessions": p.completed_sessions,
        "status": p.status,
    }


@router.get("/qr/{qr_code}")
def get_patient_by_qr(qr_code: str, db: Session = Depends(get_db)):
    p = db.query(Patient).filter(Patient.qr_code == qr_code).first()
    if not p:
        raise HTTPException(status_code=404, detail="Paciente no encontrado")
    return {
        "id": p.id,
        "full_name": p.full_name,
        "qr_code": p.qr_code,
        "total_sessions": p.total_sessions,
        "completed_sessions": p.completed_sessions,
        "status": p.status,
    }


@router.post("/")
def create_patient(payload: dict, db: Session = Depends(get_db)):
    full_name = (payload.get("full_name") or "").strip()
    if not full_name:
        raise HTTPException(status_code=400, detail="full_name es requerido")

    # ✅ Si no envían qr_code, lo generamos
    qr_code = (payload.get("qr_code") or "").strip() or _generate_qr_code(db)

    # ✅ Defaults seguros (evita 500 por NOT NULL)
    total_sessions = payload.get("total_sessions")
    completed_sessions = payload.get("completed_sessions")
    status = (payload.get("status") or "").strip()

    if total_sessions is None:
        total_sessions = 0
    if completed_sessions is None:
        completed_sessions = 0
    if not status:
        status = "Activo"

    # ✅ Evitar duplicados de QR
    existing_qr = db.query(Patient).filter(Patient.qr_code == qr_code).first()
    if existing_qr:
        raise HTTPException(status_code=400, detail="qr_code ya existe, usa otro o deja vacío")

    patient = Patient(
        full_name=full_name,
        qr_code=qr_code,
        total_sessions=int(total_sessions),
        completed_sessions=int(completed_sessions),
        status=status,
    )

    db.add(patient)
    db.commit()
    db.refresh(patient)

    return {
        "id": patient.id,
        "full_name": patient.full_name,
        "qr_code": patient.qr_code,
        "total_sessions": patient.total_sessions,
        "completed_sessions": patient.completed_sessions,
        "status": patient.status,
    }


@router.patch("/{patient_id}")
def update_patient(patient_id: int, payload: dict, db: Session = Depends(get_db)):
    p = db.query(Patient).filter(Patient.id == patient_id).first()
    if not p:
        raise HTTPException(status_code=404, detail="Paciente no encontrado")

    # Campos permitidos
    if "full_name" in payload and payload["full_name"] is not None:
        name = str(payload["full_name"]).strip()
        if name:
            p.full_name = name

    if "qr_code" in payload and payload["qr_code"] is not None:
        new_qr = str(payload["qr_code"]).strip()
        if new_qr:
            exists = db.query(Patient).filter(Patient.qr_code == new_qr, Patient.id != patient_id).first()
            if exists:
                raise HTTPException(status_code=400, detail="qr_code ya existe")
            p.qr_code = new_qr

    if "total_sessions" in payload and payload["total_sessions"] is not None:
        p.total_sessions = int(payload["total_sessions"])

    if "completed_sessions" in payload and payload["completed_sessions"] is not None:
        p.completed_sessions = int(payload["completed_sessions"])

    if "status" in payload and payload["status"] is not None:
        st = str(payload["status"]).strip()
        if st:
            p.status = st

    db.commit()
    db.refresh(p)

    return {
        "id": p.id,
        "full_name": p.full_name,
        "qr_code": p.qr_code,
        "total_sessions": p.total_sessions,
        "completed_sessions": p.completed_sessions,
        "status": p.status,
    }
