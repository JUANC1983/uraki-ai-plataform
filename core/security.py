"""Password hashing helpers shared by HTTP auth and bootstrap tooling."""

from passlib.context import CryptContext


password_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def validate_password(password: str) -> str:
    if len(password) < 12 or len(password.encode("utf-8")) > 72:
        raise ValueError("Password must contain at least 12 characters and at most 72 UTF-8 bytes")
    if "\x00" in password:
        raise ValueError("Password must not contain null characters")
    return password


def hash_password(password: str) -> str:
    return password_context.hash(validate_password(password))


def verify_password(password: str, password_hash: str) -> bool:
    # Never permit bcrypt's silent truncation to authenticate a different suffix.
    if len(password.encode("utf-8")) > 72 or "\x00" in password:
        return False
    try:
        return password_context.verify(password, password_hash)
    except (ValueError, TypeError):
        return False
