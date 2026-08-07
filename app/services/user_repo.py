"""CRUD node `:User` (dosen & mahasiswa dibedakan lewat property `role`) di Neo4j."""

from __future__ import annotations

import secrets
import uuid
from datetime import datetime, timezone
from typing import Optional

from neo4j import Session

ROLE_DOSEN = "dosen"
ROLE_MAHASISWA = "mahasiswa"


def generate_temp_password() -> str:
    return secrets.token_urlsafe(9)


def create_user(
    session: Session, nama: str, email: str, password_hash: str, role: str, nim: Optional[str] = None,
) -> dict:
    def _tx(tx):
        tx.run("CREATE CONSTRAINT user_id IF NOT EXISTS FOR (u:User) REQUIRE u.id IS UNIQUE")
        tx.run("CREATE CONSTRAINT user_email IF NOT EXISTS FOR (u:User) REQUIRE u.email IS UNIQUE")
        result = tx.run(
            """
            CREATE (u:User {
                id: $id, nama: $nama, email: $email, password_hash: $password_hash,
                role: $role, nim: $nim, aktif: true, dibuat_pada: $dibuat_pada
            })
            RETURN u
            """,
            id=str(uuid.uuid4()), nama=nama, email=email.lower().strip(), password_hash=password_hash,
            role=role, nim=nim, dibuat_pada=datetime.now(timezone.utc).isoformat(),
        )
        return dict(result.single()["u"])

    return session.execute_write(_tx)


def get_user_by_email(session: Session, email: str) -> Optional[dict]:
    def _tx(tx):
        result = tx.run("MATCH (u:User {email: $email}) RETURN u", email=email.lower().strip())
        record = result.single()
        return dict(record["u"]) if record else None

    return session.execute_read(_tx)


def get_user_by_id(session: Session, user_id: str) -> Optional[dict]:
    def _tx(tx):
        result = tx.run("MATCH (u:User {id: $id}) RETURN u", id=user_id)
        record = result.single()
        return dict(record["u"]) if record else None

    return session.execute_read(_tx)


def list_users(session: Session, role: str) -> list[dict]:
    def _tx(tx):
        result = tx.run("MATCH (u:User {role: $role}) RETURN u ORDER BY u.nama", role=role)
        return [dict(r["u"]) for r in result]

    return session.execute_read(_tx)


def set_aktif(session: Session, user_id: str, aktif: bool) -> None:
    def _tx(tx):
        tx.run("MATCH (u:User {id: $id}) SET u.aktif = $aktif", id=user_id, aktif=aktif)

    session.execute_write(_tx)


def set_password_hash(session: Session, user_id: str, password_hash: str) -> None:
    def _tx(tx):
        tx.run("MATCH (u:User {id: $id}) SET u.password_hash = $password_hash", id=user_id, password_hash=password_hash)

    session.execute_write(_tx)
