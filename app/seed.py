from app.database import SessionLocal
from app.models import Doctor

DOCTORS = [
    {
        "name": "Dra. Yiria Rosario Collantes Santos",
        "registration": "1312059627",
        "specialty": "Médico General",
    },
    {
        "name": "Dr. Miguel Andrés Herrería Rodríguez",
        "registration": "1750785220",
        "specialty": "Médico Cirujano",
    },
]

def main():
    db = SessionLocal()
    try:
        for d in DOCTORS:
            exists = db.query(Doctor).filter(Doctor.name == d["name"]).first()
            if not exists:
                db.add(Doctor(**d))
        db.commit()
        print("✅ Doctores sembrados/actualizados")
    finally:
        db.close()

if __name__ == "__main__":
    main()
