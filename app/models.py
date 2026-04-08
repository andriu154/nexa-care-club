# app/models.py
from datetime import datetime
from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, Text, Boolean, Date, Numeric
from sqlalchemy.orm import relationship

from .database import Base


class Doctor(Base):
    __tablename__ = "doctors"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)

    specialty = Column(String, nullable=True)
    registration = Column(String, unique=True, index=True, nullable=False)
    username = Column(String, unique=True, index=True, nullable=True)

    password_hash = Column(String, nullable=True)
    pin = Column(String, nullable=False, default="0000")

    role = Column(String, nullable=False, default="doctor")  # admin | doctor
    is_active = Column(Boolean, nullable=False, default=True)
    must_change_password = Column(Boolean, nullable=False, default=False)

    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, nullable=True)
    last_login_at = Column(DateTime, nullable=True)

    encounters = relationship("Encounter", back_populates="doctor")
    appointments = relationship("Appointment", back_populates="doctor")
    charges = relationship("Charge", back_populates="doctor")
    inventory_movements = relationship("InventoryMovement", back_populates="actor_doctor")


class Patient(Base):
    __tablename__ = "patients"

    id = Column(Integer, primary_key=True, index=True)

    cedula = Column(String, unique=True, index=True, nullable=True)
    phone = Column(String, nullable=True)

    full_name = Column(String, nullable=False)
    qr_code = Column(String, unique=True, index=True, nullable=True)

    birth_date = Column(Date, nullable=True)

    total_sessions = Column(Integer, default=0, nullable=False)
    completed_sessions = Column(Integer, default=0, nullable=False)

    status = Column(String, default="Activo", nullable=False)

    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, nullable=True)

    encounters = relationship("Encounter", back_populates="patient")
    attendances = relationship("Attendance", back_populates="patient")
    appointments = relationship("Appointment", back_populates="patient")
    charges = relationship("Charge", back_populates="patient")


class Appointment(Base):
    __tablename__ = "appointments"

    id = Column(Integer, primary_key=True, index=True)

    doctor_id = Column(Integer, ForeignKey("doctors.id"), nullable=False, index=True)
    patient_id = Column(Integer, ForeignKey("patients.id"), nullable=False, index=True)

    start_at = Column(DateTime, nullable=False, index=True)
    end_at = Column(DateTime, nullable=False)

    status = Column(String, default="scheduled", nullable=False)
    reason = Column(String, nullable=True)
    notes = Column(Text, nullable=True)

    encounter_id = Column(Integer, ForeignKey("encounters.id"), nullable=True, index=True)

    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, nullable=True)

    doctor = relationship("Doctor", back_populates="appointments")
    patient = relationship("Patient", back_populates="appointments")
    encounter = relationship("Encounter", back_populates="appointment", uselist=False)
    charge = relationship("Charge", back_populates="appointment", uselist=False)


class Encounter(Base):
    __tablename__ = "encounters"

    id = Column(Integer, primary_key=True, index=True)

    patient_id = Column(Integer, ForeignKey("patients.id"), nullable=False)
    doctor_id = Column(Integer, ForeignKey("doctors.id"), nullable=False)

    visit_type = Column(String, nullable=True)
    chief_complaint_short = Column(String, nullable=True)

    prescription_json = Column(Text, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    ended_at = Column(DateTime, nullable=True)
    is_signed = Column(Boolean, default=False, nullable=False)

    patient = relationship("Patient", back_populates="encounters")
    doctor = relationship("Doctor", back_populates="encounters")

    note = relationship("ClinicalNote", uselist=False, back_populates="encounter")
    evolutions = relationship("EncounterEvolution", back_populates="encounter")

    appointment = relationship("Appointment", back_populates="encounter", uselist=False)
    charge = relationship("Charge", back_populates="encounter", uselist=False)


class ClinicalNote(Base):
    __tablename__ = "clinical_notes"

    id = Column(Integer, primary_key=True, index=True)
    encounter_id = Column(Integer, ForeignKey("encounters.id"), nullable=False, unique=True)

    chief_complaint = Column(Text, nullable=True)
    hpi = Column(Text, nullable=True)

    personal_history = Column(Text, nullable=True)
    family_history = Column(Text, nullable=True)
    surgical_history = Column(Text, nullable=True)
    allergies = Column(Text, nullable=True)
    patient_sex = Column(String, nullable=True)
    last_menstrual_period = Column(String, nullable=True)

    gestas = Column(Integer, nullable=True)
    vaginal_deliveries = Column(Integer, nullable=True)
    c_sections = Column(Integer, nullable=True)
    abortions = Column(Integer, nullable=True)
    living_children = Column(Integer, nullable=True)

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
    __tablename__ = "attendance"

    id = Column(Integer, primary_key=True, index=True)

    patient_id = Column(Integer, ForeignKey("patients.id"), nullable=False)
    doctor_id = Column(Integer, ForeignKey("doctors.id"), nullable=True)

    session_number = Column(Integer, nullable=False)
    timestamp = Column(DateTime, default=datetime.utcnow, nullable=False)

    patient = relationship("Patient", back_populates="attendances")
    doctor = relationship("Doctor", backref="attendances")


class ServiceCatalog(Base):
    __tablename__ = "services"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False, unique=True, index=True)
    category = Column(String, nullable=True)
    base_price = Column(Numeric(10, 2), nullable=False, default=0)
    base_cost = Column(Numeric(10, 2), nullable=False, default=0)
    is_active = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, nullable=True)

    charges = relationship("Charge", back_populates="service")
    supply_links = relationship("ServiceSupply", back_populates="service", cascade="all, delete-orphan")


class Charge(Base):
    __tablename__ = "charges"

    id = Column(Integer, primary_key=True, index=True)

    patient_id = Column(Integer, ForeignKey("patients.id"), nullable=False, index=True)
    doctor_id = Column(Integer, ForeignKey("doctors.id"), nullable=True, index=True)
    service_id = Column(Integer, ForeignKey("services.id"), nullable=True, index=True)

    appointment_id = Column(Integer, ForeignKey("appointments.id"), nullable=True, unique=True)
    encounter_id = Column(Integer, ForeignKey("encounters.id"), nullable=True, unique=True)

    description = Column(String, nullable=True)

    subtotal = Column(Numeric(10, 2), nullable=False, default=0)
    discount = Column(Numeric(10, 2), nullable=False, default=0)
    total = Column(Numeric(10, 2), nullable=False, default=0)
    expense_amount = Column(Numeric(10, 2), nullable=False, default=0)

    payment_method = Column(String, nullable=False, default="efectivo")
    payment_status = Column(String, nullable=False, default="pendiente")  # pagado | pendiente | anulado

    charge_date = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)
    notes = Column(Text, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, nullable=True)

    patient = relationship("Patient", back_populates="charges")
    doctor = relationship("Doctor", back_populates="charges")
    service = relationship("ServiceCatalog", back_populates="charges")

    appointment = relationship("Appointment", back_populates="charge", uselist=False)
    encounter = relationship("Encounter", back_populates="charge", uselist=False)
    inventory_movements = relationship("InventoryMovement", back_populates="charge")


class InventoryItem(Base):
    __tablename__ = "inventory_items"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False, unique=True, index=True)
    category = Column(String, nullable=True)
    presentation = Column(String, nullable=True)
    unit = Column(String, nullable=False, default="unidad")  # unidad | ml | vial | ampolla | caja | jeringa | par
    current_stock = Column(Numeric(12, 2), nullable=False, default=0)
    minimum_stock = Column(Numeric(12, 2), nullable=False, default=0)
    reorder_point = Column(Numeric(12, 2), nullable=False, default=0)
    average_cost = Column(Numeric(12, 2), nullable=False, default=0)
    supplier = Column(String, nullable=True)
    notes = Column(Text, nullable=True)
    is_active = Column(Boolean, nullable=False, default=True)

    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, nullable=True)

    movements = relationship("InventoryMovement", back_populates="item", cascade="all, delete-orphan")
    service_links = relationship("ServiceSupply", back_populates="item", cascade="all, delete-orphan")


class InventoryMovement(Base):
    __tablename__ = "inventory_movements"

    id = Column(Integer, primary_key=True, index=True)

    item_id = Column(Integer, ForeignKey("inventory_items.id"), nullable=False, index=True)
    charge_id = Column(Integer, ForeignKey("charges.id"), nullable=True, index=True)
    actor_doctor_id = Column(Integer, ForeignKey("doctors.id"), nullable=True, index=True)

    movement_type = Column(String, nullable=False, default="adjustment")  # purchase | manual_in | manual_out | procedure_use | correction
    quantity = Column(Numeric(12, 2), nullable=False, default=0)
    unit_cost = Column(Numeric(12, 2), nullable=False, default=0)
    total_cost = Column(Numeric(12, 2), nullable=False, default=0)
    reference = Column(String, nullable=True)
    notes = Column(Text, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    item = relationship("InventoryItem", back_populates="movements")
    charge = relationship("Charge", back_populates="inventory_movements")
    actor_doctor = relationship("Doctor", back_populates="inventory_movements")


class ServiceSupply(Base):
    __tablename__ = "service_supplies"

    id = Column(Integer, primary_key=True, index=True)

    service_id = Column(Integer, ForeignKey("services.id"), nullable=False, index=True)
    item_id = Column(Integer, ForeignKey("inventory_items.id"), nullable=False, index=True)

    quantity = Column(Numeric(12, 2), nullable=False, default=0)
    is_optional = Column(Boolean, nullable=False, default=False)
    notes = Column(Text, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, nullable=True)

    service = relationship("ServiceCatalog", back_populates="supply_links")
    item = relationship("InventoryItem", back_populates="service_links")