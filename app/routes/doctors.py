# app/routes/doctors.py
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Doctor

router = APIRouter(prefix="/doctors", tags=["Doctors"])


@router.get("/")
def list_doctors(db: Session = Depends(get_db)):
    docs = db.query(Doctor).order_by(Doctor.name.asc()).all()
    return [
        {
            "id": d.id,
            "name": d.name,
            "specialty": d.specialty,
            "registration": d.registration,
            "username": d.username,
            "role": d.role,
            "is_active": d.is_active,
            "must_change_password": d.must_change_password,
        }
        for d in docs
    ]