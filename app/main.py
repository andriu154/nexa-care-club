from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware
import os

from .database import engine
from .models import Base

from .routes.doctors import router as doctors_router
from .routes.auth import router as auth_router            # ✅ Login UI (/login, /logout)
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

# 1) crear tablas (SQLite)
Base.metadata.create_all(bind=engine)

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
