from fastapi import FastAPI
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

# ✅ PDF + Historial
from .routes.pdf import router as pdf_router
from .routes.history import router as history_router


app = FastAPI(title="NexaCenter")

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
app.include_router(encounters_router)
app.include_router(clinical_notes_router)

# ✅ nuevas rutas
app.include_router(pdf_router)
app.include_router(history_router)


@app.get("/")
def root():
    return {"status": "ok", "message": "NexaCenter funcionando ✅"}
