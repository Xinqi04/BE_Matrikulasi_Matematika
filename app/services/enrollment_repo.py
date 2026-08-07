"""Assignment mahasiswa ke Modul lewat relationship `(:User)-[:MENGAMBIL]->(:Modul)`. Mahasiswa
cuma bisa lihat/kerjain Bab dari Modul yang dia ambil -- lihat `kg_queries.list_modul_untuk_mahasiswa`
dan pemakaian `mahasiswa_terdaftar_bab` di router mahasiswa.
"""

from __future__ import annotations

from neo4j import Session


def set_modul_mahasiswa(session: Session, mahasiswa_id: str, modul_ids: list[str]) -> None:
    """Replace semantics: assignment lama dihapus semua, diganti sesuai `modul_ids`. List kosong
    berarti mahasiswa dicabut dari semua Modul -- itu perilaku yang disengaja."""

    def _tx(tx):
        tx.run(
            "MATCH (u:User {id: $mahasiswa_id})-[r:MENGAMBIL]->(:Modul) DELETE r",
            mahasiswa_id=mahasiswa_id,
        )
        tx.run(
            """
            MATCH (u:User {id: $mahasiswa_id})
            UNWIND $modul_ids AS modul_id
            MATCH (m:Modul {id: modul_id})
            MERGE (u)-[:MENGAMBIL]->(m)
            """,
            mahasiswa_id=mahasiswa_id, modul_ids=modul_ids,
        )

    session.execute_write(_tx)


def list_modul_ids_mahasiswa(session: Session, mahasiswa_id: str) -> list[str]:
    def _tx(tx):
        result = tx.run(
            "MATCH (:User {id: $mahasiswa_id})-[:MENGAMBIL]->(m:Modul) RETURN m.id AS id ORDER BY m.id",
            mahasiswa_id=mahasiswa_id,
        )
        return [r["id"] for r in result]

    return session.execute_read(_tx)


def mahasiswa_terdaftar_bab(session: Session, mahasiswa_id: str, bab_id: str) -> bool:
    """True kalau Modul pemilik `bab_id` sudah diambil mahasiswa ini. `bab_id` yang gak
    ada Modul-nya sama sekali dianggap False (fail closed)."""

    def _tx(tx):
        result = tx.run(
            """
            MATCH (m:Modul)-[:HAS_BAB]->(:Bab {id: $bab_id})
            OPTIONAL MATCH (:User {id: $mahasiswa_id})-[r:MENGAMBIL]->(m)
            RETURN r IS NOT NULL AS terdaftar
            """,
            bab_id=bab_id, mahasiswa_id=mahasiswa_id,
        )
        record = result.single()
        return bool(record and record["terdaftar"])

    return session.execute_read(_tx)
