from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware
import os

from sqlalchemy import text
from passlib.context import CryptContext

from .database import engine, SessionLocal
from .models import Base, Doctor

# Routers API
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

# Routers UI
from .routes.ui import router as ui_router
from .routes.appointments_ui import router as appointments_ui_router


app = FastAPI(title="NexaCenter")

# 🔐 Middleware de sesión (LOGIN UI)
app.add_middleware(
    SessionMiddleware,
    secret_key=os.getenv("SESSION_SECRET", "dev-secret-change-me"),
    same_site="lax",
    https_only=True,
)

# ✅ hash de contraseñas
pwd_context = CryptContext(
    schemes=["pbkdf2_sha256", "bcrypt"],
    deprecated="auto",
)


def ensure_sqlite_schema():
    """
    SQLite no se migra solo con create_all().
    Esto agrega columnas faltantes en tablas ya existentes.
    """
    try:
        with engine.begin() as conn:
            # doctors
            tbl = conn.execute(
                text("SELECT name FROM sqlite_master WHERE type='table' AND name='doctors';")
            ).fetchone()
            if tbl:
                cols = conn.execute(text("PRAGMA table_info(doctors);")).fetchall()
                col_names = {c[1] for c in cols}

                if "specialty" not in col_names:
                    conn.execute(text("ALTER TABLE doctors ADD COLUMN specialty VARCHAR;"))
                    print("✅ Migración: doctors.specialty agregado")

                if "registration" not in col_names:
                    conn.execute(text("ALTER TABLE doctors ADD COLUMN registration VARCHAR;"))
                    print("✅ Migración: doctors.registration agregado")

                if "password_hash" not in col_names:
                    conn.execute(text("ALTER TABLE doctors ADD COLUMN password_hash VARCHAR;"))
                    print("✅ Migración: doctors.password_hash agregado")

                if "pin" not in col_names:
                    conn.execute(text("ALTER TABLE doctors ADD COLUMN pin VARCHAR NOT NULL DEFAULT '0000';"))
                    print("✅ Migración: doctors.pin agregado")

            # patients (por si Render tiene DB vieja)
            tblp = conn.execute(
                text("SELECT name FROM sqlite_master WHERE type='table' AND name='patients';")
            ).fetchone()
            if tblp:
                cols = conn.execute(text("PRAGMA table_info(patients);")).fetchall()
                col_names = {c[1] for c in cols}

                if "cedula" not in col_names:
                    conn.execute(text("ALTER TABLE patients ADD COLUMN cedula VARCHAR;"))
                    print("✅ Migración: patients.cedula agregado")

                if "phone" not in col_names:
                    conn.execute(text("ALTER TABLE patients ADD COLUMN phone VARCHAR;"))
                    print("✅ Migración: patients.phone agregado")

                if "created_at" not in col_names:
                    conn.execute(text("ALTER TABLE patients ADD COLUMN created_at DATETIME;"))
                    print("✅ Migración: patients.created_at agregado (nullable por SQLite ALTER)")

                if "updated_at" not in col_names:
                    conn.execute(text("ALTER TABLE patients ADD COLUMN updated_at DATETIME;"))
                    print("✅ Migración: patients.updated_at agregado")

    except Exception as e:
        print("⚠️ Error en migración SQLite:", repr(e))


def seed_default_doctors_if_enabled():
    """
    Crea doctores desde variables de entorno (Render).
    Solo corre si SEED_DEFAULT_DOCTORS=1.
    """
    if os.getenv("SEED_DEFAULT_DOCTORS", "0") != "1":
        return

    reg1 = (os.getenv("SEED_DOCTOR_1_REG") or "").strip()
    pass1 = (os.getenv("SEED_DOCTOR_1_PASS") or "").strip()
    name1 = (os.getenv("SEED_DOCTOR_1_NAME") or "Doctor 1").strip()

    reg2 = (os.getenv("SEED_DOCTOR_2_REG") or "").strip()
    pass2 = (os.getenv("SEED_DOCTOR_2_PASS") or "").strip()
    name2 = (os.getenv("SEED_DOCTOR_2_NAME") or "Doctor 2").strip()

    pairs = []
    if reg1 and pass1:
        pairs.append((reg1, pass1, name1))
    if reg2 and pass2:
        pairs.append((reg2, pass2, name2))

    if not pairs:
        print("⚠️ SEED_DEFAULT_DOCTORS=1 pero faltan variables SEED_DOCTOR_*")
        return

    db = SessionLocal()
    try:
        for reg, plain_pass, name in pairs:
            existing = db.query(Doctor).filter(Doctor.registration == reg).first()
            if existing:
                print(f"ℹ️ Doctor ya existe (registration={reg}). No se modifica.")
                continue

            hashed = pwd_context.hash(plain_pass)

            d = Doctor(
                name=name,
                registration=reg,
                specialty=None,
                password_hash=hashed,
                pin="0000",
            )
            db.add(d)
            db.commit()
            print(f"✅ Doctor creado: {name} (registration={reg})")

    except Exception as e:
        db.rollback()
        print("⚠️ Error creando doctores seed:", repr(e))
    finally:
        db.close()


# 1️⃣ crear tablas
Base.metadata.create_all(bind=engine)

# 2️⃣ migraciones SQLite
ensure_sqlite_schema()

# 3️⃣ seed doctores
seed_default_doctors_if_enabled()

# 4️⃣ rutas API
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

# 5️⃣ rutas UI (ESTO ES LO QUE TE FALTABA / SE ROMPIÓ)
app.include_router(ui_router)
app.include_router(appointments_ui_router)

# 6️⃣ archivos estáticos
app.mount("/static", StaticFiles(directory="app/static"), name="static")


@app.get("/")
def root():
    return {"status": "ok", "message": "NexaCenter funcionando ✅"}