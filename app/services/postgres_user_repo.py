from __future__ import annotations

import secrets
from typing import Optional

from app.postgres_client import postgres_connection

ROLES = {"admin", "dosen", "mahasiswa"}


def generate_temp_password() -> str:
    return secrets.token_urlsafe(9)


def get_by_nim(nim: str) -> Optional[dict]:
    with postgres_connection() as conn:
        return conn.execute("SELECT * FROM users WHERE nim = %s", (nim.strip(),)).fetchone()


def get_by_id(user_id: str) -> Optional[dict]:
    with postgres_connection() as conn:
        return conn.execute("SELECT * FROM users WHERE id = %s", (user_id,)).fetchone()


def list_users(role: str | None = None) -> list[dict]:
    with postgres_connection() as conn:
        if role:
            rows = conn.execute("SELECT id, nama, nim, role, aktif FROM users WHERE role = %s ORDER BY nama", (role,)).fetchall()
        else:
            rows = conn.execute("SELECT id, nama, nim, role, aktif FROM users ORDER BY role, nama").fetchall()
    return [{**row, "id": str(row["id"])} for row in rows]


def create_user(nama: str, nim: str, password_hash: str, role: str) -> dict:
    if role not in ROLES:
        raise ValueError("Role tidak valid")
    with postgres_connection() as conn:
        return conn.execute(
            """INSERT INTO users (nama, nim, password_hash, role)
               VALUES (%s, %s, %s, %s) RETURNING id, nama, nim, role, aktif""",
            (nama.strip(), nim.strip(), password_hash, role),
        ).fetchone()


def set_active(user_id: str, active: bool) -> Optional[dict]:
    with postgres_connection() as conn:
        user = conn.execute(
            "UPDATE users SET aktif = %s, updated_at = now() WHERE id = %s RETURNING id, nama, nim, role, aktif",
            (active, user_id),
        ).fetchone()
    return {**user, "id": str(user["id"])} if user else None


def update_user(
    user_id: str, nama: str, nim: str, aktif: bool, password_hash: str | None = None,
) -> Optional[dict]:
    with postgres_connection() as conn:
        if password_hash:
            user = conn.execute(
                """UPDATE users
                   SET nama = %s, nim = %s, aktif = %s, password_hash = %s, updated_at = now()
                   WHERE id = %s RETURNING id, nama, nim, role, aktif""",
                (nama.strip(), nim.strip(), aktif, password_hash, user_id),
            ).fetchone()
        else:
            user = conn.execute(
                """UPDATE users
                   SET nama = %s, nim = %s, aktif = %s, updated_at = now()
                   WHERE id = %s RETURNING id, nama, nim, role, aktif""",
                (nama.strip(), nim.strip(), aktif, user_id),
            ).fetchone()
    return {**user, "id": str(user["id"])} if user else None


def set_password_hash(user_id: str, password_hash: str) -> None:
    with postgres_connection() as conn:
        conn.execute("UPDATE users SET password_hash = %s, updated_at = now() WHERE id = %s", (password_hash, user_id))
