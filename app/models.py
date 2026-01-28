from datetime import datetime
from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, Text, Boolean
from sqlalchemy.orm import relationship

from .database import Base


class Doctor(Base):
    __tablename__ = "doctors"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)

    # ✅ NUEVO
    specialty = Column(String, nullable=True)     # "Médico General", "Médico Cirujano"
    registration = Column(String, nullable=True)  # "1312059627", "1750785220"

    encounters = relationship("Encounter", back_populates="doctor")


class Patient(Base):
    __tablename__ = "patients"

    id = Column(Integer, primary_key=True, index=True)

    full_name = Column(String, nullable=False)

    # ✅ NECESARIO para check-in por QR
    qr_code = Column(String, unique=True, index=True, nullable=True)

    # ✅ NECESARIO para control de sesiones
    total_sessions = Column(Integer, default=0, nullable=False)
    completed_sessions = Column(Integer, default=0, nullable=False)

    # ✅ NECESARIO para estado
    status = Column(String, default="Activo", nullable=False)

    encounters = relationship("Encounter", back_populates="patient")
    attendances = relationship("Attendance", back_populates="patient")



class Encounter(Base):
    __tablename__ = "encounters"

    id = Column(Integer, primary_key=True, index=True)

    patient_id = Column(Integer, ForeignKey("patients.id"), nullable=False)
    doctor_id = Column(Integer, ForeignKey("doctors.id"), nullable=False)

    visit_type = Column(String, nullable=True)
    chief_complaint_short = Column(String, nullable=True)

    # ✅ NUEVO (control ventana 20 min)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    ended_at = Column(DateTime, nullable=True)  # cuando terminó la atención
    is_signed = Column(Boolean, default=False, nullable=False)

    patient = relationship("Patient", back_populates="encounters")
    doctor = relationship("Doctor", back_populates="encounters")

    note = relationship("ClinicalNote", uselist=False, back_populates="encounter")
    evolutions = relationship("EncounterEvolution", back_populates="encounter")


class ClinicalNote(Base):
    __tablename__ = "clinical_notes"

    id = Column(Integer, primary_key=True, index=True)
    encounter_id = Column(Integer, ForeignKey("encounters.id"), nullable=False, unique=True)

    chief_complaint = Column(Text, nullable=True)
    hpi = Column(Text, nullable=True)

    physical_exam = Column(Text, nullable=True)
    complementary_tests = Column(Text, nullable=True)
    assessment_dx = Column(Text, nullable=True)
    plan_treatment = Column(Text, nullable=True)
    indications_alarm_signs = Column(Text, nullable=True)
    follow_up = Column(Text, nullable=True)

    ta_sys = Column(Integer, nullable=True)
    ta_dia = Column(Integer, nullable=True)
    hr = Column(Integer, nullable=True)
    rr = Column(Integer, nullable=True)
    temp = Column(String, nullable=True)
    spo2 = Column(Integer, nullable=True)

    encounter = relationship("Encounter", back_populates="note")


class EncounterEvolution(Base):
    __tablename__ = "encounter_evolutions"

    id = Column(Integer, primary_key=True, index=True)
    encounter_id = Column(Integer, ForeignKey("encounters.id"), nullable=False)

    author_doctor_id = Column(Integer, ForeignKey("doctors.id"), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    content = Column(Text, nullable=False)

    encounter = relationship("Encounter", back_populates="evolutions")
class Attendance(Base):
    __tablename__ = "attendance"  # ✅ SINGULAR (igual que tu DB)

    id = Column(Integer, primary_key=True, index=True)

    patient_id = Column(Integer, ForeignKey("patients.id"), nullable=False)
    doctor_id = Column(Integer, ForeignKey("doctors.id"), nullable=True)

    session_number = Column(Integer, nullable=False)
    timestamp = Column(DateTime, default=datetime.utcnow, nullable=False)

    # ✅ back_populates debe coincidir EXACTO con Patient.attendances
    patient = relationship("Patient", back_populates="attendances")

    # ✅ nombre plural para consistencia
    doctor = relationship("Doctor", backref="attendances")
