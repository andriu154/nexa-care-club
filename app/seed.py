# app/seed.py
from app.database import SessionLocal
from app.models import Doctor
from app.deps.passwords import hash_password

DOCTORS = [
    {
        "name": "Dra. Yiria Rosario Collantes Santos",
        "registration": "1312059627",
        "username": "yiria",
        "specialty": "Médico General",
        "role": "admin",
        "password_plain": "Nexa2026*Yiria",
    },
    {
        "name": "Dr. Miguel Andrés Herrería Rodríguez",
        "registration": "1750785220",
        "username": "andres",
        "specialty": "Médico Cirujano",
        "role": "admin"
        "password_plain": "Nexa2026*Miguel",
    },
]


def main():
    db = SessionLocal()
    try:
        for d in DOCTORS:
            doc = db.query(Doctor).filter(Doctor.registration == d["registration"]).first()

            if not doc:
                doc = db.query(Doctor).filter(Doctor.name == d["name"]).first()

            if not doc:
                doc = Doctor(
                    name=d["name"],
                    registration=d["registration"],
                    username=d["username"],
                    specialty=d["specialty"],
                    role=d["role"],
                    is_active=True,
                    must_change_password=False,
                    password_hash=hash_password(d["password_plain"]),
                    pin="0000",
                )
                db.add(doc)
            else:
                doc.name = d["name"]
                doc.registration = d["registration"]
                doc.username = d["username"]
                doc.specialty = d["specialty"]
                doc.role = d["role"]
                doc.is_active = True

                if not getattr(doc, "password_hash", None):
                    doc.password_hash = hash_password(d["password_plain"])

        db.commit()
        print("✅ Doctores sembrados/actualizados con roles, usuario y password_hash")
        print("🔐 Credenciales iniciales:")
        for d in DOCTORS:
            print(
                f"   - {d['name']} | usuario: {d['username']} | registro: {d['registration']} | pass: {d['password_plain']}"
            )
    finally:
        db.close()


if __name__ == "__main__":
    main()