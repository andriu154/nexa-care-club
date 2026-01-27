from fastapi import FastAPI
from .database import engine, SessionLocal
from .models import Base
from .seed import seed_doctors

from .routes.doctors import router as doctors_router
from .routes.auth import router as auth_router
from .routes.patients import router as patients_router
from .routes.checkin import router as checkin_router
from .routes.export import router as export_router
from .routes.scan import router as scan_router
from .routes.ui import router as ui_router
from .routes.encounters import router as encounters_router
from .routes.clinical_notes import router as clinical_notes_router

app = FastAPI(title="Nexa Care Club")

# 1) crear tablas
Base.metadata.create_all(bind=engine)

# 2) seed doctores al iniciar (una sola vez)
db = SessionLocal()
seed_doctors(db)
db.close()

# 3) rutas
app.include_router(doctors_router)
app.include_router(auth_router)
app.include_router(patients_router)
app.include_router(checkin_router)
app.include_router(export_router)
app.include_router(scan_router)
app.include_router(ui_router)
app.include_router(encounters_router)
app.include_router(clinical_notes_router)

@app.get("/")
def root():
    return {"status": "ok", "message": "Nexa Care Club funcionando ✅"}
