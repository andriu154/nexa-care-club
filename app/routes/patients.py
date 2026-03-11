from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from datetime import datetime
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
        code = "QR-" + secrets.token_hex(4).upper()
        exists = db.query(Patient).filter(Patient.qr_code == code).first()
        if not exists:
            return code


def _clean_cedula(s: str) -> str:
    return "".join(ch for ch in (s or "") if ch.isdigit()).strip()


def _parse_birth_date(value):
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        return datetime.strptime(raw, "%Y-%m-%d").date()
    except Exception:
        raise HTTPException(status_code=400, detail="birth_date debe tener formato YYYY-MM-DD")


def _patient_age(patient: Patient) -> int | None:
    birth_date = getattr(patient, "birth_date", None)
    if not birth_date:
        return None

    today = datetime.utcnow().date()
    years = today.year - birth_date.year - (
        (today.month, today.day) < (birth_date.month, birth_date.day)
    )
    return years


def _serialize_patient(p: Patient) -> dict:
    return {
        "id": p.id,
        "cedula": p.cedula,
        "full_name": p.full_name,
        "phone": p.phone,
        "qr_code": p.qr_code,
        "birth_date": p.birth_date.isoformat() if p.birth_date else None,
        "age": _patient_age(p),
        "total_sessions": p.total_sessions,
        "completed_sessions": p.completed_sessions,
        "status": p.status,
    }


@router.get("/")
def list_patients(db: Session = Depends(get_db)):
    patients = db.query(Patient).order_by(Patient.id.desc()).all()
    return [_serialize_patient(p) for p in patients]


@router.get("/{patient_id}")
def get_patient(patient_id: int, db: Session = Depends(get_db)):
    p = db.query(Patient).filter(Patient.id == patient_id).first()
    if not p:
        raise HTTPException(status_code=404, detail="Paciente no encontrado")
    return _serialize_patient(p)


@router.get("/cedula/{cedula}")
def get_patient_by_cedula(cedula: str, db: Session = Depends(get_db)):
    ced = _clean_cedula(cedula)
    if not ced:
        raise HTTPException(status_code=400, detail="Cédula inválida")

    p = db.query(Patient).filter(Patient.cedula == ced).first()
    if not p:
        raise HTTPException(status_code=404, detail="Paciente no encontrado")

    return _serialize_patient(p)


@router.get("/qr/{qr_code}")
def get_patient_by_qr(qr_code: str, db: Session = Depends(get_db)):
    p = db.query(Patient).filter(Patient.qr_code == qr_code).first()
    if not p:
        raise HTTPException(status_code=404, detail="Paciente no encontrado")
    return _serialize_patient(p)


@router.post("/")
def create_patient(payload: dict, db: Session = Depends(get_db)):
    full_name = (payload.get("full_name") or "").strip()
    if not full_name:
        raise HTTPException(status_code=400, detail="full_name es requerido")

    cedula = _clean_cedula(payload.get("cedula") or "")
    if cedula:
        exists_c = db.query(Patient).filter(Patient.cedula == cedula).first()
        if exists_c:
            raise HTTPException(status_code=400, detail="cedula ya existe")

    phone = (payload.get("phone") or "").strip() or None
    birth_date = _parse_birth_date(payload.get("birth_date"))

    qr_code = (payload.get("qr_code") or "").strip() or _generate_qr_code(db)

    total_sessions = payload.get("total_sessions")
    completed_sessions = payload.get("completed_sessions")
    status = (payload.get("status") or "").strip()

    if total_sessions is None:
        total_sessions = 0
    if completed_sessions is None:
        completed_sessions = 0
    if not status:
        status = "Activo"

    existing_qr = db.query(Patient).filter(Patient.qr_code == qr_code).first()
    if existing_qr:
        raise HTTPException(status_code=400, detail="qr_code ya existe, usa otro o deja vacío")

    patient = Patient(
        cedula=cedula or None,
        full_name=full_name,
        phone=phone,
        qr_code=qr_code,
        birth_date=birth_date,
        total_sessions=int(total_sessions),
        completed_sessions=int(completed_sessions),
        status=status,
    )

    db.add(patient)
    db.commit()
    db.refresh(patient)

    return _serialize_patient(patient)


@router.patch("/{patient_id}")
def update_patient(patient_id: int, payload: dict, db: Session = Depends(get_db)):
    p = db.query(Patient).filter(Patient.id == patient_id).first()
    if not p:
        raise HTTPException(status_code=404, detail="Paciente no encontrado")

    if "full_name" in payload and payload["full_name"] is not None:
        name = str(payload["full_name"]).strip()
        if name:
            p.full_name = name

    if "cedula" in payload and payload["cedula"] is not None:
        ced = _clean_cedula(str(payload["cedula"]))
        if ced:
            exists = db.query(Patient).filter(Patient.cedula == ced, Patient.id != patient_id).first()
            if exists:
                raise HTTPException(status_code=400, detail="cedula ya existe")
            p.cedula = ced
        else:
            p.cedula = None

    if "phone" in payload and payload["phone"] is not None:
        ph = str(payload["phone"]).strip()
        p.phone = ph or None

    if "birth_date" in payload:
        p.birth_date = _parse_birth_date(payload.get("birth_date"))

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

    return _serialize_patient(p)