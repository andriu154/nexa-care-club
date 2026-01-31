from app.database import SessionLocal
from app.models import Doctor
from app.deps.passwords import hash_password

DOCTORS = [
    {
        "name": "Dra. Yiria Rosario Collantes Santos",
        "registration": "1312059627",
        "specialty": "Médico General",
        "password_plain": "Nexa2026*Yiria",
    },
    {
        "name": "Dr. Miguel Andrés Herrería Rodríguez",
        "registration": "1750785220",
        "specialty": "Médico Cirujano",
        "password_plain": "Nexa2026*Miguel",
    },
]


def main():
    db = SessionLocal()
    try:
        for d in DOCTORS:
            doc = db.query(Doctor).filter(Doctor.registration == d["registration"]).first()

            if not doc:
                # si no existe por registration, intenta por nombre
                doc = db.query(Doctor).filter(Doctor.name == d["name"]).first()

            if not doc:
                doc = Doctor(
                    name=d["name"],
                    registration=d["registration"],
                    specialty=d["specialty"],
                    password_hash=hash_password(d["password_plain"]),
                )
                db.add(doc)
            else:
                # actualiza datos clave
                doc.name = d["name"]
                doc.registration = d["registration"]
                doc.specialty = d["specialty"]

                # si no tiene password, asigna uno inicial
                if not getattr(doc, "password_hash", None):
                    doc.password_hash = hash_password(d["password_plain"])

        db.commit()
        print("✅ Doctores sembrados/actualizados con password_hash")
        print("🔐 Credenciales iniciales:")
        for d in DOCTORS:
            print(f"   - {d['name']} | usuario(registro): {d['registration']} | pass: {d['password_plain']}")
    finally:
        db.close()


if __name__ == "__main__":
    main()
