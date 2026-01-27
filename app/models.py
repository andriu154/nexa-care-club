# app/models.py
from sqlalchemy import Column, Integer, String, DateTime, ForeignKey
from datetime import datetime
from .database import Base

class Doctor(Base):
    __tablename__ = "doctors"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, unique=True, index=True, nullable=False)
    pin = Column(String, nullable=False)

class Patient(Base):
    __tablename__ = "patients"
    id = Column(Integer, primary_key=True, index=True)
    full_name = Column(String, index=True, nullable=False)
    qr_code = Column(String, unique=True, index=True, nullable=False)

    total_sessions = Column(Integer, default=7, nullable=False)
    completed_sessions = Column(Integer, default=0, nullable=False)
    status = Column(String, default="Activo", nullable=False)  # Activo | Completado

    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

class Attendance(Base):
    __tablename__ = "attendance"
    id = Column(Integer, primary_key=True, index=True)

    patient_id = Column(Integer, ForeignKey("patients.id"), nullable=False)
    doctor_id = Column(Integer, ForeignKey("doctors.id"), nullable=False)

    session_number = Column(Integer, nullable=False)
    timestamp = Column(DateTime, default=datetime.utcnow, nullable=False)
