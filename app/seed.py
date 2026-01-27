# app/seed.py
from sqlalchemy.orm import Session
from .models import Doctor

def seed_doctors(db: Session):
    # Si ya existen doctores, no volver a insertar
    existing = db.query(Doctor).count()
    if existing > 0:
        return

    doctors = [
        Doctor(name="Dra. Yiria Collantes", pin="1234"),
        Doctor(name="Dr. Andrés Herrería", pin="5678"),
    ]
    db.add_all(doctors)
    db.commit()
