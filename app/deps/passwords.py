# app/deps/passwords.py
from passlib.context import CryptContext

pwd_context = CryptContext(
    schemes=["pbkdf2_sha256", "bcrypt"],
    deprecated="auto",
)


def hash_password(plain: str) -> str:
    return pwd_context.hash((plain or "").strip())


def verify_password(plain: str, hashed: str) -> bool:
    return pwd_context.verify((plain or "").strip(), hashed or "")