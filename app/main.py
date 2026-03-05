from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware
import os
from pathlib import Path

from sqlalchemy import text
from passlib.context import CryptContext

from .database import engine, SessionLocal
from .models import Base, Doctor

from .routes.doctors import router as doctors_router
from .routes.auth import router as auth_router
from .routes.patients import router as patients_router
from .routes.checkin import router as checkin_router
from .routes.export import router as export_router
from .routes.scan import router as scan_router
from .routes.ui import router as ui_router
from .routes.encounters import router as encounters_router
from .routes.clinical_notes import router as clinical_notes_router
from .routes.pdf import router as pdf_router
from .routes.history import router as history_router
from .routes.appointments_ui import router as appointments_ui_router


# ===== Paths robustos (funciona igual en Render y local) =====
BASE_DIR = Path(__file__).resolve().parent          # .../app
TEMPLATES_DIR = BASE_DIR / "templates"             # .../app/templates
STATIC_DIR = BASE_DIR / "static"                   # .../app/static


app = FastAPI(title="NexaCenter")

# ===== Sesiones (Login UI) =====
# En Render debes usar HTTPS (https_only=True).
# En local normalmente NO (https_only=False) para no romper cookies.
ENV = (os.getenv("ENV") or os.getenv("RENDER") or "").lower()
IS_PROD = ENV in ("production", "prod", "true", "1") or os.getenv("RENDER") is not None

SESSION_SECRET = os.getenv("SESSION_SECRET", "dev-secret-change-me")
if SESSION_SECRET == "dev-secret-change-me" and IS_PROD:
    # No rompe el deploy, pero te avisa en logs
    print("⚠️ SESSION_SECRET está en default. Configúralo en Render Environment Variables.")

app.add_middleware(
    SessionMiddleware,
    secret_key=SESSION_SECRET,
    same_site="lax",
    https_only=IS_PROD,  # ✅ en producción True, en local False
)

# ===== Hash de contraseñas =====
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
            tbl = conn.execute(
                text("SELECT name FROM sqlite_master WHERE type='table' AND name='doctors';")
            ).fetchone()

            if not tbl:
                print("ℹ️ Tabla doctors no existe todavía.")
                return

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
                conn.execute(
                    text("ALTER TABLE doctors ADD COLUMN pin VARCHAR NOT NULL DEFAULT '0000';")
                )
                print("✅ Migración: doctors.pin agregado")

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


# ===== 1) Crear tablas =====
Base.metadata.create_all(bind=engine)

# ===== 2) Migraciones SQLite =====
ensure_sqlite_schema()

# ===== 3) Seed doctores =====
seed_default_doctors_if_enabled()

# ===== 4) Rutas =====
app.include_router(auth_router)
app.include_router(doctors_router)
app.include_router(patients_router)
app.include_router(checkin_router)
app.include_router(export_router)
app.include_router(scan_router)

app.include_router(ui_router)
app.include_router(appointments_ui_router)
app.include_router(encounters_router)
app.include_router(clinical_notes_router)

app.include_router(pdf_router)
app.include_router(history_router)

# ===== 5) Archivos estáticos =====
# Si no existe, no rompas el arranque en producción:
if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
else:
    print(f"⚠️ STATIC_DIR no existe: {STATIC_DIR}")


@app.get("/")
def root():
    return {"status": "ok", "message": "NexaCenter funcionando ✅"}