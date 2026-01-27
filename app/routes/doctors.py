from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from ..database import get_db
from ..models import Doctor

router = APIRouter(prefix="/doctors", tags=["Doctors"])

@router.get("/")
def list_doctors(db: Session = Depends(get_db)):
    docs = db.query(Doctor).all()
    return [{"id": d.id, "name": d.name} for d in docs]
