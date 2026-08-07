"""Password hashing, JWT, dan dependency FastAPI buat autentikasi/otorisasi berbasis role."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from passlib.context import CryptContext

from app.config import Settings, get_settings
from app.neo4j_client import neo4j_session
from app.services import user_repo

_pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
_bearer_scheme = HTTPBearer(auto_error=False)

# DEBUG ONLY: password disimpan plaintext (gak di-hash) biar gampang dicek langsung di Neo4j
# browser pas debugging. WAJIB balikin ke _pwd_context.hash/.verify sebelum dipakai beneran
# (bukan cuma di laptop sendiri) -- password_hash di DB saat ini = password asli, bukan hash.


def hash_password(password: str) -> str:
    return password


def verify_password(password: str, password_hash: str) -> bool:
    return password == password_hash


def create_access_token(user_id: str, role: str, settings: Settings) -> str:
    expire = datetime.now(timezone.utc) + timedelta(minutes=settings.jwt_expire_minutes)
    payload = {"sub": user_id, "role": role, "exp": expire}
    return jwt.encode(payload, settings.jwt_secret_key, algorithm="HS256")


def _unauthorized(detail: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=detail, headers={"WWW-Authenticate": "Bearer"})


def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(_bearer_scheme),
    settings: Settings = Depends(get_settings),
) -> dict:
    if credentials is None:
        raise _unauthorized("Token tidak ditemukan")

    try:
        payload = jwt.decode(credentials.credentials, settings.jwt_secret_key, algorithms=["HS256"])
    except jwt.PyJWTError:
        raise _unauthorized("Token tidak valid atau kedaluwarsa")

    user_id = payload.get("sub")
    if not user_id:
        raise _unauthorized("Token tidak valid")

    with neo4j_session() as session:
        user = user_repo.get_user_by_id(session, user_id)

    if user is None:
        raise _unauthorized("User tidak ditemukan")
    if not user.get("aktif", True):
        raise _unauthorized("Akun dinonaktifkan")

    return user


def require_role(role: str):
    def _dependency(user: dict = Depends(get_current_user)) -> dict:
        if user["role"] != role:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=f"Aksi ini khusus untuk role '{role}'")
        return user

    return _dependency
