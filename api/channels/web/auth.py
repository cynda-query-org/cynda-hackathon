"""Web channel auth helpers — password hashing and session dependency."""
import bcrypt

from fastapi import Cookie, Header, HTTPException


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def verify_password(password: str, password_hash: str) -> bool:
    return bcrypt.checkpw(password.encode(), password_hash.encode())


async def get_current_user(
    cynda_session: str | None = Cookie(None),
    authorization: str | None = Header(None),
) -> dict:
    token = None
    if authorization and authorization.startswith("Bearer "):
        token = authorization[7:]
    if not token:
        token = cynda_session
    if not token:
        raise HTTPException(status_code=401, detail="Not authenticated")
    from api.db import get_session_user
    user = get_session_user(token)
    if not user:
        raise HTTPException(status_code=401, detail="Invalid or expired session")
    return user
