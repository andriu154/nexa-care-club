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
from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, Text, Float, func
from sqlalchemy.orm import relationship

# -----------------------------
# CONSULTAS (Encounters)
# -----------------------------
class Encounter(Base):
    __tablename__ = "encounters"

    id = Column(Integer, primary_key=True, index=True)

    patient_id = Column(Integer, ForeignKey("patients.id"), nullable=False, index=True)
    doctor_id = Column(Integer, ForeignKey("doctors.id"), nullable=False, index=True)

    visit_type = Column(String(20), nullable=False)  # "primera_vez" | "control"
    chief_complaint_short = Column(String(200), nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())

    note = relationship("ClinicalNote", back_populates="encounter", uselist=False)


# -----------------------------
# NOTA CLÍNICA (Historia de la consulta)
# 1 nota por consulta
# -----------------------------
class ClinicalNote(Base):
    __tablename__ = "clinical_notes"

    id = Column(Integer, primary_key=True, index=True)
    encounter_id = Column(Integer, ForeignKey("encounters.id"), nullable=False, unique=True, index=True)

    # Texto clínico (MG)
    chief_complaint = Column(Text, nullable=True)          # Motivo de consulta
    hpi = Column(Text, nullable=True)                      # Enfermedad actual
    past_history = Column(Text, nullable=True)             # Antecedentes
    allergies = Column(Text, nullable=True)
    medications = Column(Text, nullable=True)
    family_history = Column(Text, nullable=True)
    social_history = Column(Text, nullable=True)
    review_of_systems = Column(Text, nullable=True)
    physical_exam = Column(Text, nullable=True)
    complementary_tests = Column(Text, nullable=True)
    assessment_dx = Column(Text, nullable=True)
    plan_treatment = Column(Text, nullable=True)
    indications_alarm_signs = Column(Text, nullable=True)
    follow_up = Column(Text, nullable=True)

    # Signos vitales (estructurado)
    ta_sys = Column(Integer, nullable=True)
    ta_dia = Column(Integer, nullable=True)
    hr = Column(Integer, nullable=True)
    rr = Column(Integer, nullable=True)
    temp = Column(Float, nullable=True)
    spo2 = Column(Integer, nullable=True)
    weight = Column(Float, nullable=True)
    height = Column(Float, nullable=True)
    bmi = Column(Float, nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())

    encounter = relationship("Encounter", back_populates="note")
