from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware
import os

from sqlalchemy import text

from .database import engine
from .models import Base

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


app = FastAPI(title="NexaCenter")

# 🔐 Middleware de sesión (LOGIN UI) — SOLO UNA VEZ
app.add_middleware(
    SessionMiddleware,
    secret_key=os.getenv("SESSION_SECRET", "dev-secret-change-me"),
    same_site="lax",
    https_only=True,  # Render usa HTTPS
)


# =========================
# ✅ MIGRACIÓN SIMPLE SQLITE
# =========================
def ensure_sqlite_schema():
    """
    SQLite no se migra solo con create_all().
    Esto asegura que columnas nuevas existan en tablas viejas.
    """
    try:
        with engine.begin() as conn:
            # Ver columnas actuales de doctors
            cols = conn.execute(text("PRAGMA table_info(doctors);")).fetchall()
            col_names = {c[1] for c in cols}  # c[1] = name

            # Si falta specialty, la agregamos
            if "specialty" not in col_names:
                conn.execute(text("ALTER TABLE doctors ADD COLUMN specialty VARCHAR;"))
                print("✅ Migración aplicada: doctors.specialty agregado")

    except Exception as e:
        print("⚠️ Error en migración SQLite:", e)


# 1) crear tablas (si no existen)
Base.metadata.create_all(bind=engine)

# 1.1) aplicar migraciones simples
ensure_sqlite_schema()

# 2) rutas
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

# 3) archivos estáticos
app.mount("/static", StaticFiles(directory="app/static"), name="static")


@app.get("/")
def root():
    return {"status": "ok", "message": "NexaCenter funcionando ✅"}