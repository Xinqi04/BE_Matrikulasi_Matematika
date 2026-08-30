"""Enrollment mahasiswa ke modul dengan PostgreSQL sebagai source of truth."""

from __future__ import annotations

from neo4j import Session

from app.postgres_client import postgres_connection


def set_modul_mahasiswa(mahasiswa_id: str, modul_ids: list[str]) -> None:
    modul_ids = list(dict.fromkeys(modul_ids))
    with postgres_connection() as conn:
        conn.execute("DELETE FROM enrollments WHERE student_id = %s", (mahasiswa_id,))
        if modul_ids:
            with conn.cursor() as cursor:
                cursor.executemany(
                    "INSERT INTO enrollments (student_id, module_id) VALUES (%s, %s)",
                    [(mahasiswa_id, modul_id) for modul_id in modul_ids],
                )


def list_modul_ids_mahasiswa(mahasiswa_id: str) -> list[str]:
    with postgres_connection() as conn:
        rows = conn.execute(
            "SELECT module_id FROM enrollments WHERE student_id = %s ORDER BY module_id",
            (mahasiswa_id,),
        ).fetchall()
    return [row["module_id"] for row in rows]


def list_mahasiswa_terdaftar() -> list[dict]:
    with postgres_connection() as conn:
        rows = conn.execute(
            """
            SELECT u.id, u.nama, u.nim, u.aktif,
                   array_agg(e.module_id ORDER BY e.module_id) AS modul_ids
            FROM users u
            JOIN enrollments e ON e.student_id = u.id
            WHERE u.role = 'mahasiswa'
            GROUP BY u.id, u.nama, u.nim, u.aktif
            ORDER BY u.nama
            """
        ).fetchall()
    return [{**row, "id": str(row["id"])} for row in rows]


def mahasiswa_terdaftar_bab(session: Session, mahasiswa_id: str, bab_id: str) -> bool:
    """True kalau Modul pemilik `bab_id` sudah diambil mahasiswa ini. `bab_id` yang gak
    ada Modul-nya sama sekali dianggap False (fail closed)."""

    def _tx(tx):
        record = tx.run(
            "MATCH (m:Modul)-[:HAS_BAB]->(:Bab {id: $bab_id}) RETURN m.id AS modul_id LIMIT 1",
            bab_id=bab_id,
        ).single()
        return record["modul_id"] if record else None

    modul_id = session.execute_read(_tx)
    return bool(modul_id and modul_id in list_modul_ids_mahasiswa(mahasiswa_id))
