# app/database.py
import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base

# ✅ 1) Usa Postgres en deploy (si existe DATABASE_URL), si no usa SQLite local
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./nexa_care_club.db")

# ✅ 2) Compatibilidad: algunos proveedores dan postgres:// y SQLAlchemy espera postgresql://
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

# ✅ 3) connect_args solo para SQLite
connect_args = {}
if DATABASE_URL.startswith("sqlite"):
    connect_args = {"check_same_thread": False}

# ✅ 4) Engine
engine = create_engine(DATABASE_URL, connect_args=connect_args)

# ✅ 5) Session
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# ✅ 6) Base para modelos
Base = declarative_base()

# ✅ 7) Dependencia FastAPI
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
