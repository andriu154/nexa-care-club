# app/main.py
from datetime import datetime
from fastapi import FastAPI, Request
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware
import os

from sqlalchemy import text
from passlib.context import CryptContext

from .database import engine, SessionLocal
from .models import Base, Doctor, ServiceCatalog

from .routes.doctors import router as doctors_router
from .routes.auth import router as auth_router
from .routes.patients import router as patients_router
from .routes.checkin import router as checkin_router
from .routes.export import router as export_router
from .routes.scan import router as scan_router
from .routes.encounters import router as encounters_router
from .routes.clinical_notes import router as clinical_notes_router
from .routes.pdf import router as pdf_router
from .routes.history import router as history_router
from .routes.ui import router as ui_router
from .routes.appointments_ui import router as appointments_ui_router
from .routes.professionals_ui import router as professionals_ui_router
from .routes.finances_ui import router as finances_ui_router

app = FastAPI(title="NexaCenter")

app.add_middleware(
    SessionMiddleware,
    secret_key=os.getenv("SESSION_SECRET", "dev-secret-change-me"),
    same_site="lax",
    https_only=True,
)

pwd_context = CryptContext(
    schemes=["pbkdf2_sha256", "bcrypt"],
    deprecated="auto",
)


def _db_dialect() -> str:
    try:
        return engine.dialect.name
    except Exception:
        return ""


def _is_sqlite_engine() -> bool:
    return _db_dialect() == "sqlite"


def _is_postgres_engine() -> bool:
    return _db_dialect() in {"postgresql", "postgres"}


def ensure_sqlite_schema():
    if not _is_sqlite_engine():
        return

    try:
        with engine.begin() as conn:
            tbl = conn.execute(
                text("SELECT name FROM sqlite_master WHERE type='table' AND name='doctors';")
            ).fetchone()
            if tbl:
                cols = conn.execute(text("PRAGMA table_info(doctors);")).fetchall()
                col_names = {c[1] for c in cols}

                if "specialty" not in col_names:
                    conn.execute(text("ALTER TABLE doctors ADD COLUMN specialty VARCHAR;"))
                    print("✅ Migración SQLite: doctors.specialty agregado")

                if "registration" not in col_names:
                    conn.execute(text("ALTER TABLE doctors ADD COLUMN registration VARCHAR;"))
                    print("✅ Migración SQLite: doctors.registration agregado")

                if "password_hash" not in col_names:
                    conn.execute(text("ALTER TABLE doctors ADD COLUMN password_hash VARCHAR;"))
                    print("✅ Migración SQLite: doctors.password_hash agregado")

                if "pin" not in col_names:
                    conn.execute(text("ALTER TABLE doctors ADD COLUMN pin VARCHAR NOT NULL DEFAULT '0000';"))
                    print("✅ Migración SQLite: doctors.pin agregado")

                if "username" not in col_names:
                    conn.execute(text("ALTER TABLE doctors ADD COLUMN username VARCHAR;"))
                    print("✅ Migración SQLite: doctors.username agregado")

                if "role" not in col_names:
                    conn.execute(text("ALTER TABLE doctors ADD COLUMN role VARCHAR NOT NULL DEFAULT 'doctor';"))
                    print("✅ Migración SQLite: doctors.role agregado")

                if "is_active" not in col_names:
                    conn.execute(text("ALTER TABLE doctors ADD COLUMN is_active BOOLEAN NOT NULL DEFAULT 1;"))
                    print("✅ Migración SQLite: doctors.is_active agregado")

                if "must_change_password" not in col_names:
                    conn.execute(text("ALTER TABLE doctors ADD COLUMN must_change_password BOOLEAN NOT NULL DEFAULT 0;"))
                    print("✅ Migración SQLite: doctors.must_change_password agregado")

                if "created_at" not in col_names:
                    conn.execute(text("ALTER TABLE doctors ADD COLUMN created_at DATETIME;"))
                    print("✅ Migración SQLite: doctors.created_at agregado")

                if "updated_at" not in col_names:
                    conn.execute(text("ALTER TABLE doctors ADD COLUMN updated_at DATETIME;"))
                    print("✅ Migración SQLite: doctors.updated_at agregado")

                if "last_login_at" not in col_names:
                    conn.execute(text("ALTER TABLE doctors ADD COLUMN last_login_at DATETIME;"))
                    print("✅ Migración SQLite: doctors.last_login_at agregado")

                conn.execute(text("UPDATE doctors SET role = 'doctor' WHERE role IS NULL OR TRIM(role) = '';"))
                conn.execute(text("UPDATE doctors SET is_active = 1 WHERE is_active IS NULL;"))
                conn.execute(text("UPDATE doctors SET must_change_password = 0 WHERE must_change_password IS NULL;"))
                conn.execute(text("UPDATE doctors SET created_at = CURRENT_TIMESTAMP WHERE created_at IS NULL;"))

                conn.execute(text(
                    "CREATE UNIQUE INDEX IF NOT EXISTS ix_doctors_username_unique "
                    "ON doctors(username) WHERE username IS NOT NULL;"
                ))

            tblp = conn.execute(
                text("SELECT name FROM sqlite_master WHERE type='table' AND name='patients';")
            ).fetchone()
            if tblp:
                cols = conn.execute(text("PRAGMA table_info(patients);")).fetchall()
                col_names = {c[1] for c in cols}

                if "cedula" not in col_names:
                    conn.execute(text("ALTER TABLE patients ADD COLUMN cedula VARCHAR;"))
                    print("✅ Migración SQLite: patients.cedula agregado")

                if "phone" not in col_names:
                    conn.execute(text("ALTER TABLE patients ADD COLUMN phone VARCHAR;"))
                    print("✅ Migración SQLite: patients.phone agregado")

                if "created_at" not in col_names:
                    conn.execute(text("ALTER TABLE patients ADD COLUMN created_at DATETIME;"))
                    print("✅ Migración SQLite: patients.created_at agregado")

                if "updated_at" not in col_names:
                    conn.execute(text("ALTER TABLE patients ADD COLUMN updated_at DATETIME;"))
                    print("✅ Migración SQLite: patients.updated_at agregado")

            tble = conn.execute(
                text("SELECT name FROM sqlite_master WHERE type='table' AND name='encounters';")
            ).fetchone()
            if tble:
                cols = conn.execute(text("PRAGMA table_info(encounters);")).fetchall()
                col_names = {c[1] for c in cols}

                if "prescription_json" not in col_names:
                    conn.execute(text("ALTER TABLE encounters ADD COLUMN prescription_json TEXT;"))
                    print("✅ Migración SQLite: encounters.prescription_json agregado")

            tbls = conn.execute(
                text("SELECT name FROM sqlite_master WHERE type='table' AND name='services';")
            ).fetchone()
            if tbls:
                cols = conn.execute(text("PRAGMA table_info(services);")).fetchall()
                col_names = {c[1] for c in cols}

                if "category" not in col_names:
                    conn.execute(text("ALTER TABLE services ADD COLUMN category VARCHAR;"))
                    print("✅ Migración SQLite: services.category agregado")

                if "base_price" not in col_names:
                    conn.execute(text("ALTER TABLE services ADD COLUMN base_price NUMERIC(10,2) NOT NULL DEFAULT 0;"))
                    print("✅ Migración SQLite: services.base_price agregado")

                if "base_cost" not in col_names:
                    conn.execute(text("ALTER TABLE services ADD COLUMN base_cost NUMERIC(10,2) NOT NULL DEFAULT 0;"))
                    print("✅ Migración SQLite: services.base_cost agregado")

                if "is_active" not in col_names:
                    conn.execute(text("ALTER TABLE services ADD COLUMN is_active BOOLEAN NOT NULL DEFAULT 1;"))
                    print("✅ Migración SQLite: services.is_active agregado")

                if "created_at" not in col_names:
                    conn.execute(text("ALTER TABLE services ADD COLUMN created_at DATETIME;"))
                    print("✅ Migración SQLite: services.created_at agregado")

                if "updated_at" not in col_names:
                    conn.execute(text("ALTER TABLE services ADD COLUMN updated_at DATETIME;"))
                    print("✅ Migración SQLite: services.updated_at agregado")

            tblc = conn.execute(
                text("SELECT name FROM sqlite_master WHERE type='table' AND name='charges';")
            ).fetchone()
            if tblc:
                cols = conn.execute(text("PRAGMA table_info(charges);")).fetchall()
                col_names = {c[1] for c in cols}

                needed = {
                    "patient_id": "INTEGER",
                    "doctor_id": "INTEGER",
                    "service_id": "INTEGER",
                    "appointment_id": "INTEGER",
                    "encounter_id": "INTEGER",
                    "description": "VARCHAR",
                    "subtotal": "NUMERIC(10,2)",
                    "discount": "NUMERIC(10,2)",
                    "total": "NUMERIC(10,2)",
                    "expense_amount": "NUMERIC(10,2) NOT NULL DEFAULT 0",
                    "payment_method": "VARCHAR",
                    "payment_status": "VARCHAR",
                    "charge_date": "DATETIME",
                    "notes": "TEXT",
                    "created_at": "DATETIME",
                    "updated_at": "DATETIME",
                }
                for col_name, col_type in needed.items():
                    if col_name not in col_names:
                        conn.execute(text(f"ALTER TABLE charges ADD COLUMN {col_name} {col_type};"))
                        print(f"✅ Migración SQLite: charges.{col_name} agregado")

            tbli = conn.execute(
                text("SELECT name FROM sqlite_master WHERE type='table' AND name='inventory_items';")
            ).fetchone()
            if tbli:
                cols = conn.execute(text("PRAGMA table_info(inventory_items);")).fetchall()
                col_names = {c[1] for c in cols}

                inventory_needed = {
                    "name": "VARCHAR",
                    "category": "VARCHAR",
                    "presentation": "VARCHAR",
                    "unit": "VARCHAR NOT NULL DEFAULT 'unidad'",
                    "current_stock": "NUMERIC(12,2) NOT NULL DEFAULT 0",
                    "minimum_stock": "NUMERIC(12,2) NOT NULL DEFAULT 0",
                    "reorder_point": "NUMERIC(12,2) NOT NULL DEFAULT 0",
                    "average_cost": "NUMERIC(12,2) NOT NULL DEFAULT 0",
                    "supplier": "VARCHAR",
                    "notes": "TEXT",
                    "is_active": "BOOLEAN NOT NULL DEFAULT 1",
                    "created_at": "DATETIME",
                    "updated_at": "DATETIME",
                }
                for col_name, col_type in inventory_needed.items():
                    if col_name not in col_names:
                        conn.execute(text(f"ALTER TABLE inventory_items ADD COLUMN {col_name} {col_type};"))
                        print(f"✅ Migración SQLite: inventory_items.{col_name} agregado")

            tblm = conn.execute(
                text("SELECT name FROM sqlite_master WHERE type='table' AND name='inventory_movements';")
            ).fetchone()
            if tblm:
                cols = conn.execute(text("PRAGMA table_info(inventory_movements);")).fetchall()
                col_names = {c[1] for c in cols}

                movement_needed = {
                    "item_id": "INTEGER",
                    "charge_id": "INTEGER",
                    "actor_doctor_id": "INTEGER",
                    "movement_type": "VARCHAR NOT NULL DEFAULT 'adjustment'",
                    "quantity": "NUMERIC(12,2) NOT NULL DEFAULT 0",
                    "unit_cost": "NUMERIC(12,2) NOT NULL DEFAULT 0",
                    "total_cost": "NUMERIC(12,2) NOT NULL DEFAULT 0",
                    "reference": "VARCHAR",
                    "notes": "TEXT",
                    "created_at": "DATETIME",
                }
                for col_name, col_type in movement_needed.items():
                    if col_name not in col_names:
                        conn.execute(text(f"ALTER TABLE inventory_movements ADD COLUMN {col_name} {col_type};"))
                        print(f"✅ Migración SQLite: inventory_movements.{col_name} agregado")

            tblss = conn.execute(
                text("SELECT name FROM sqlite_master WHERE type='table' AND name='service_supplies';")
            ).fetchone()
            if tblss:
                cols = conn.execute(text("PRAGMA table_info(service_supplies);")).fetchall()
                col_names = {c[1] for c in cols}

                supply_needed = {
                    "service_id": "INTEGER",
                    "item_id": "INTEGER",
                    "quantity": "NUMERIC(12,2) NOT NULL DEFAULT 0",
                    "is_optional": "BOOLEAN NOT NULL DEFAULT 0",
                    "notes": "TEXT",
                    "created_at": "DATETIME",
                    "updated_at": "DATETIME",
                }
                for col_name, col_type in supply_needed.items():
                    if col_name not in col_names:
                        conn.execute(text(f"ALTER TABLE service_supplies ADD COLUMN {col_name} {col_type};"))
                        print(f"✅ Migración SQLite: service_supplies.{col_name} agregado")

    except Exception as e:
        print("⚠️ Error en migración SQLite:", repr(e))


def ensure_postgres_schema():
    if not _is_postgres_engine():
        return

    try:
        with engine.begin() as conn:
            doctor_columns = {
                "specialty": "ALTER TABLE doctors ADD COLUMN specialty VARCHAR;",
                "registration": "ALTER TABLE doctors ADD COLUMN registration VARCHAR;",
                "password_hash": "ALTER TABLE doctors ADD COLUMN password_hash VARCHAR;",
                "pin": "ALTER TABLE doctors ADD COLUMN pin VARCHAR NOT NULL DEFAULT '0000';",
                "username": "ALTER TABLE doctors ADD COLUMN username VARCHAR;",
                "role": "ALTER TABLE doctors ADD COLUMN role VARCHAR NOT NULL DEFAULT 'doctor';",
                "is_active": "ALTER TABLE doctors ADD COLUMN is_active BOOLEAN NOT NULL DEFAULT TRUE;",
                "must_change_password": "ALTER TABLE doctors ADD COLUMN must_change_password BOOLEAN NOT NULL DEFAULT FALSE;",
                "created_at": "ALTER TABLE doctors ADD COLUMN created_at TIMESTAMP;",
                "updated_at": "ALTER TABLE doctors ADD COLUMN updated_at TIMESTAMP;",
                "last_login_at": "ALTER TABLE doctors ADD COLUMN last_login_at TIMESTAMP;",
            }

            for col_name, sql in doctor_columns.items():
                exists = conn.execute(text(f"""
                    SELECT 1
                    FROM information_schema.columns
                    WHERE table_name = 'doctors' AND column_name = '{col_name}'
                    LIMIT 1
                """)).fetchone()
                if not exists:
                    conn.execute(text(sql))
                    print(f"✅ Migración PostgreSQL: doctors.{col_name} agregado")

            conn.execute(text("UPDATE doctors SET role = 'doctor' WHERE role IS NULL OR BTRIM(role) = '';"))
            conn.execute(text("UPDATE doctors SET is_active = TRUE WHERE is_active IS NULL;"))
            conn.execute(text("UPDATE doctors SET must_change_password = FALSE WHERE must_change_password IS NULL;"))
            conn.execute(text("UPDATE doctors SET created_at = NOW() WHERE created_at IS NULL;"))
            conn.execute(text(
                "CREATE UNIQUE INDEX IF NOT EXISTS ix_doctors_username_unique "
                "ON doctors(username) WHERE username IS NOT NULL;"
            ))

            patient_columns = {
                "cedula": "ALTER TABLE patients ADD COLUMN cedula VARCHAR;",
                "phone": "ALTER TABLE patients ADD COLUMN phone VARCHAR;",
                "created_at": "ALTER TABLE patients ADD COLUMN created_at TIMESTAMP;",
                "updated_at": "ALTER TABLE patients ADD COLUMN updated_at TIMESTAMP;",
            }

            for col_name, sql in patient_columns.items():
                exists = conn.execute(text(f"""
                    SELECT 1
                    FROM information_schema.columns
                    WHERE table_name = 'patients' AND column_name = '{col_name}'
                    LIMIT 1
                """)).fetchone()
                if not exists:
                    conn.execute(text(sql))
                    print(f"✅ Migración PostgreSQL: patients.{col_name} agregado")

            exists = conn.execute(text("""
                SELECT 1
                FROM information_schema.columns
                WHERE table_name = 'encounters' AND column_name = 'prescription_json'
                LIMIT 1
            """)).fetchone()
            if not exists:
                conn.execute(text("ALTER TABLE encounters ADD COLUMN prescription_json TEXT;"))
                print("✅ Migración PostgreSQL: encounters.prescription_json agregado")

            service_columns = {
                "category": "ALTER TABLE services ADD COLUMN category VARCHAR;",
                "base_price": "ALTER TABLE services ADD COLUMN base_price NUMERIC(10,2) NOT NULL DEFAULT 0;",
                "base_cost": "ALTER TABLE services ADD COLUMN base_cost NUMERIC(10,2) NOT NULL DEFAULT 0;",
                "is_active": "ALTER TABLE services ADD COLUMN is_active BOOLEAN NOT NULL DEFAULT TRUE;",
                "created_at": "ALTER TABLE services ADD COLUMN created_at TIMESTAMP;",
                "updated_at": "ALTER TABLE services ADD COLUMN updated_at TIMESTAMP;",
            }

            for col_name, sql in service_columns.items():
                exists = conn.execute(text(f"""
                    SELECT 1
                    FROM information_schema.columns
                    WHERE table_name = 'services' AND column_name = '{col_name}'
                    LIMIT 1
                """)).fetchone()
                if not exists:
                    conn.execute(text(sql))
                    print(f"✅ Migración PostgreSQL: services.{col_name} agregado")

            charge_columns = {
                "patient_id": "ALTER TABLE charges ADD COLUMN patient_id INTEGER;",
                "doctor_id": "ALTER TABLE charges ADD COLUMN doctor_id INTEGER;",
                "service_id": "ALTER TABLE charges ADD COLUMN service_id INTEGER;",
                "appointment_id": "ALTER TABLE charges ADD COLUMN appointment_id INTEGER;",
                "encounter_id": "ALTER TABLE charges ADD COLUMN encounter_id INTEGER;",
                "description": "ALTER TABLE charges ADD COLUMN description VARCHAR;",
                "subtotal": "ALTER TABLE charges ADD COLUMN subtotal NUMERIC(10,2) NOT NULL DEFAULT 0;",
                "discount": "ALTER TABLE charges ADD COLUMN discount NUMERIC(10,2) NOT NULL DEFAULT 0;",
                "total": "ALTER TABLE charges ADD COLUMN total NUMERIC(10,2) NOT NULL DEFAULT 0;",
                "expense_amount": "ALTER TABLE charges ADD COLUMN expense_amount NUMERIC(10,2) NOT NULL DEFAULT 0;",
                "payment_method": "ALTER TABLE charges ADD COLUMN payment_method VARCHAR NOT NULL DEFAULT 'efectivo';",
                "payment_status": "ALTER TABLE charges ADD COLUMN payment_status VARCHAR NOT NULL DEFAULT 'pendiente';",
                "charge_date": "ALTER TABLE charges ADD COLUMN charge_date TIMESTAMP;",
                "notes": "ALTER TABLE charges ADD COLUMN notes TEXT;",
                "created_at": "ALTER TABLE charges ADD COLUMN created_at TIMESTAMP;",
                "updated_at": "ALTER TABLE charges ADD COLUMN updated_at TIMESTAMP;",
            }

            for col_name, sql in charge_columns.items():
                exists = conn.execute(text(f"""
                    SELECT 1
                    FROM information_schema.columns
                    WHERE table_name = 'charges' AND column_name = '{col_name}'
                    LIMIT 1
                """)).fetchone()
                if not exists:
                    conn.execute(text(sql))
                    print(f"✅ Migración PostgreSQL: charges.{col_name} agregado")

            inventory_columns = {
                "name": "ALTER TABLE inventory_items ADD COLUMN name VARCHAR;",
                "category": "ALTER TABLE inventory_items ADD COLUMN category VARCHAR;",
                "presentation": "ALTER TABLE inventory_items ADD COLUMN presentation VARCHAR;",
                "unit": "ALTER TABLE inventory_items ADD COLUMN unit VARCHAR NOT NULL DEFAULT 'unidad';",
                "current_stock": "ALTER TABLE inventory_items ADD COLUMN current_stock NUMERIC(12,2) NOT NULL DEFAULT 0;",
                "minimum_stock": "ALTER TABLE inventory_items ADD COLUMN minimum_stock NUMERIC(12,2) NOT NULL DEFAULT 0;",
                "reorder_point": "ALTER TABLE inventory_items ADD COLUMN reorder_point NUMERIC(12,2) NOT NULL DEFAULT 0;",
                "average_cost": "ALTER TABLE inventory_items ADD COLUMN average_cost NUMERIC(12,2) NOT NULL DEFAULT 0;",
                "supplier": "ALTER TABLE inventory_items ADD COLUMN supplier VARCHAR;",
                "notes": "ALTER TABLE inventory_items ADD COLUMN notes TEXT;",
                "is_active": "ALTER TABLE inventory_items ADD COLUMN is_active BOOLEAN NOT NULL DEFAULT TRUE;",
                "created_at": "ALTER TABLE inventory_items ADD COLUMN created_at TIMESTAMP;",
                "updated_at": "ALTER TABLE inventory_items ADD COLUMN updated_at TIMESTAMP;",
            }

            for col_name, sql in inventory_columns.items():
                exists = conn.execute(text(f"""
                    SELECT 1
                    FROM information_schema.columns
                    WHERE table_name = 'inventory_items' AND column_name = '{col_name}'
                    LIMIT 1
                """)).fetchone()
                if not exists:
                    conn.execute(text(sql))
                    print(f"✅ Migración PostgreSQL: inventory_items.{col_name} agregado")

            movement_columns = {
                "item_id": "ALTER TABLE inventory_movements ADD COLUMN item_id INTEGER;",
                "charge_id": "ALTER TABLE inventory_movements ADD COLUMN charge_id INTEGER;",
                "actor_doctor_id": "ALTER TABLE inventory_movements ADD COLUMN actor_doctor_id INTEGER;",
                "movement_type": "ALTER TABLE inventory_movements ADD COLUMN movement_type VARCHAR NOT NULL DEFAULT 'adjustment';",
                "quantity": "ALTER TABLE inventory_movements ADD COLUMN quantity NUMERIC(12,2) NOT NULL DEFAULT 0;",
                "unit_cost": "ALTER TABLE inventory_movements ADD COLUMN unit_cost NUMERIC(12,2) NOT NULL DEFAULT 0;",
                "total_cost": "ALTER TABLE inventory_movements ADD COLUMN total_cost NUMERIC(12,2) NOT NULL DEFAULT 0;",
                "reference": "ALTER TABLE inventory_movements ADD COLUMN reference VARCHAR;",
                "notes": "ALTER TABLE inventory_movements ADD COLUMN notes TEXT;",
                "created_at": "ALTER TABLE inventory_movements ADD COLUMN created_at TIMESTAMP;",
            }

            for col_name, sql in movement_columns.items():
                exists = conn.execute(text(f"""
                    SELECT 1
                    FROM information_schema.columns
                    WHERE table_name = 'inventory_movements' AND column_name = '{col_name}'
                    LIMIT 1
                """)).fetchone()
                if not exists:
                    conn.execute(text(sql))
                    print(f"✅ Migración PostgreSQL: inventory_movements.{col_name} agregado")

            supply_columns = {
                "service_id": "ALTER TABLE service_supplies ADD COLUMN service_id INTEGER;",
                "item_id": "ALTER TABLE service_supplies ADD COLUMN item_id INTEGER;",
                "quantity": "ALTER TABLE service_supplies ADD COLUMN quantity NUMERIC(12,2) NOT NULL DEFAULT 0;",
                "is_optional": "ALTER TABLE service_supplies ADD COLUMN is_optional BOOLEAN NOT NULL DEFAULT FALSE;",
                "notes": "ALTER TABLE service_supplies ADD COLUMN notes TEXT;",
                "created_at": "ALTER TABLE service_supplies ADD COLUMN created_at TIMESTAMP;",
                "updated_at": "ALTER TABLE service_supplies ADD COLUMN updated_at TIMESTAMP;",
            }

            for col_name, sql in supply_columns.items():
                exists = conn.execute(text(f"""
                    SELECT 1
                    FROM information_schema.columns
                    WHERE table_name = 'service_supplies' AND column_name = '{col_name}'
                    LIMIT 1
                """)).fetchone()
                if not exists:
                    conn.execute(text(sql))
                    print(f"✅ Migración PostgreSQL: service_supplies.{col_name} agregado")

    except Exception as e:
        print("⚠️ Error en migración PostgreSQL:", repr(e))


def ensure_database_schema():
    dialect = _db_dialect()
    print(f"ℹ️ Motor de base de datos detectado: {dialect or 'desconocido'}")

    if _is_sqlite_engine():
        ensure_sqlite_schema()
        return

    if _is_postgres_engine():
        ensure_postgres_schema()
        return

    print("ℹ️ No hay migraciones manuales configuradas para este motor de base de datos.")


def ensure_default_admin_exists():
    db = SessionLocal()
    try:
        admin = db.query(Doctor).filter(Doctor.role == "admin").first()
        if admin:
            return

        first_doctor = db.query(Doctor).order_by(Doctor.id.asc()).first()
        if not first_doctor:
            return

        first_doctor.role = "admin"
        first_doctor.is_active = True
        first_doctor.updated_at = first_doctor.updated_at or first_doctor.created_at
        db.commit()
        print(f"✅ Se asignó admin inicial a: {first_doctor.name}")
    except Exception as e:
        db.rollback()
        print("⚠️ Error asignando admin inicial:", repr(e))
    finally:
        db.close()


def seed_default_doctors_if_enabled():
    if os.getenv("SEED_DEFAULT_DOCTORS", "0") != "1":
        return

    reg1 = (os.getenv("SEED_DOCTOR_1_REG") or "").strip()
    pass1 = (os.getenv("SEED_DOCTOR_1_PASS") or "").strip()
    name1 = (os.getenv("SEED_DOCTOR_1_NAME") or "Doctor 1").strip()
    user1 = (os.getenv("SEED_DOCTOR_1_USER") or reg1).strip().lower()
    role1 = (os.getenv("SEED_DOCTOR_1_ROLE") or "admin").strip().lower()

    reg2 = (os.getenv("SEED_DOCTOR_2_REG") or "").strip()
    pass2 = (os.getenv("SEED_DOCTOR_2_PASS") or "").strip()
    name2 = (os.getenv("SEED_DOCTOR_2_NAME") or "Doctor 2").strip()
    user2 = (os.getenv("SEED_DOCTOR_2_USER") or reg2).strip().lower()
    role2 = (os.getenv("SEED_DOCTOR_2_ROLE") or "doctor").strip().lower()

    pairs = []
    if reg1 and pass1:
        pairs.append((reg1, pass1, name1, user1, role1))
    if reg2 and pass2:
        pairs.append((reg2, pass2, name2, user2, role2))

    if not pairs:
        print("⚠️ SEED_DEFAULT_DOCTORS=1 pero faltan variables SEED_DOCTOR_*")
        return

    db = SessionLocal()
    try:
        for reg, plain_pass, name, username, role in pairs:
            existing = db.query(Doctor).filter(Doctor.registration == reg).first()
            if existing:
                if not existing.username:
                    existing.username = username
                if not existing.role:
                    existing.role = role
                if not existing.password_hash:
                    existing.password_hash = pwd_context.hash(plain_pass)
                    existing.must_change_password = False
                existing.is_active = True
                existing.updated_at = existing.updated_at or existing.created_at
                db.commit()
                print(f"ℹ️ Doctor ya existe (registration={reg}). Se actualizó lo faltante.")
                continue

            hashed = pwd_context.hash(plain_pass)
            d = Doctor(
                name=name,
                registration=reg,
                username=username,
                specialty=None,
                password_hash=hashed,
                pin="0000",
                role=role,
                is_active=True,
                must_change_password=False,
            )
            db.add(d)
            db.commit()
            print(f"✅ Doctor creado: {name} (registration={reg}, username={username})")

    except Exception as e:
        db.rollback()
        print("⚠️ Error creando doctores seed:", repr(e))
    finally:
        db.close()


def seed_default_services():
    defaults = [
        ("Consulta médica general", "Consulta", 25.00, 0.00),
        ("Control subsecuente", "Consulta", 20.00, 0.00),
        ("Certificado médico", "Documento", 15.00, 0.00),
        ("Procedimiento menor", "Procedimiento", 35.00, 5.00),
        ("Teleconsulta", "Consulta", 20.00, 0.00),
    ]

    db = SessionLocal()
    try:
        for name, category, base_price, base_cost in defaults:
            existing = db.query(ServiceCatalog).filter(ServiceCatalog.name == name).first()
            if existing:
                if not existing.category:
                    existing.category = category
                if existing.base_price is None or float(existing.base_price or 0) <= 0:
                    existing.base_price = base_price
                if existing.base_cost is None or float(existing.base_cost or 0) < 0:
                    existing.base_cost = base_cost
                if existing.is_active is None:
                    existing.is_active = True
                existing.updated_at = datetime.utcnow()
                continue

            item = ServiceCatalog(
                name=name,
                category=category,
                base_price=base_price,
                base_cost=base_cost,
                is_active=True,
                created_at=datetime.utcnow(),
                updated_at=datetime.utcnow(),
            )
            db.add(item)

        db.commit()
        print("✅ Servicios base verificados")
    except Exception as e:
        db.rollback()
        print("⚠️ Error creando servicios base:", repr(e))
    finally:
        db.close()


@app.middleware("http")
async def enforce_password_change(request: Request, call_next):
    path = request.url.path

    exempt_prefixes = (
        "/login",
        "/logout",
        "/change-password",
        "/static",
        "/docs",
        "/openapi.json",
        "/redoc",
        "/favicon.ico",
    )

    if path.startswith(exempt_prefixes):
        return await call_next(request)

    if "session" not in request.scope:
        return await call_next(request)

    session = request.scope.get("session") or {}
    doctor_id = session.get("doctor_id")

    if doctor_id:
        db = SessionLocal()
        try:
            doctor = db.query(Doctor).filter(Doctor.id == int(doctor_id)).first()
            if doctor and doctor.must_change_password:
                return RedirectResponse(url="/change-password", status_code=302)
        finally:
            db.close()

    return await call_next(request)


Base.metadata.create_all(bind=engine)
ensure_database_schema()
seed_default_doctors_if_enabled()
ensure_default_admin_exists()
seed_default_services()

app.include_router(auth_router)
app.include_router(doctors_router)
app.include_router(patients_router)
app.include_router(checkin_router)
app.include_router(export_router)
app.include_router(scan_router)
app.include_router(encounters_router)
app.include_router(clinical_notes_router)
app.include_router(pdf_router)
app.include_router(history_router)

app.include_router(ui_router)
app.include_router(appointments_ui_router)
app.include_router(professionals_ui_router)
app.include_router(finances_ui_router)

app.mount("/static", StaticFiles(directory="app/static"), name="static")


@app.get("/")
def root():
    return {"status": "ok", "message": "NexaCenter funcionando ✅"}