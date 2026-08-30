"""Mutasi manual struktur Modul/Bab/Konsep oleh dosen."""

from __future__ import annotations

from uuid import uuid4

from neo4j import Session


def update_modul(session: Session, modul_id: str, nama: str) -> dict | None:
    def _tx(tx):
        record = tx.run(
            "MATCH (m:Modul {id: $id}) SET m.nama_domain = $nama RETURN m.id AS id, m.nama_domain AS nama",
            id=modul_id, nama=nama.strip(),
        ).single()
        return dict(record) if record else None
    return session.execute_write(_tx)


def create_bab(session: Session, modul_id: str, nama: str, nomor: str | None) -> dict | None:
    bab_id = f"bab_{uuid4().hex}"

    def _tx(tx):
        record = tx.run(
            """
            MATCH (m:Modul {id: $modul_id})
            OPTIONAL MATCH (m)-[:HAS_BAB]->(existing:Bab)
            WITH m, coalesce(max(toInteger(existing.nomor)), 0) + 1 AS nomor_berikut
            CREATE (b:Bab {id: $bab_id, nama: $nama, nomor: coalesce($nomor, toString(nomor_berikut))})
            CREATE (m)-[:HAS_BAB]->(b)
            RETURN b.id AS id, b.nama AS nama, b.nomor AS nomor
            """,
            modul_id=modul_id, bab_id=bab_id, nama=nama.strip(), nomor=nomor.strip() if nomor else None,
        ).single()
        return dict(record) if record else None
    return session.execute_write(_tx)


def update_bab(session: Session, bab_id: str, nama: str) -> dict | None:
    def _tx(tx):
        record = tx.run(
            "MATCH (b:Bab {id: $id}) SET b.nama = $nama RETURN b.id AS id, b.nama AS nama, b.nomor AS nomor",
            id=bab_id, nama=nama.strip(),
        ).single()
        return dict(record) if record else None
    return session.execute_write(_tx)


def add_konsep(session: Session, owner_id: str, nama: str, deskripsi: str = "") -> dict | None:
    def _tx(tx):
        record = tx.run(
            """
            MATCH (owner) WHERE (owner:Bab OR owner:SubBab) AND owner.id = $owner_id
            MERGE (k:Konsep {nama: $nama})
            ON CREATE SET k.deskripsi = $deskripsi
            MERGE (owner)-[:HAS_KONSEP]->(k)
            RETURN k.nama AS nama
            """,
            owner_id=owner_id, nama=nama.strip(), deskripsi=deskripsi.strip(),
        ).single()
        return dict(record) if record else None
    return session.execute_write(_tx)


def rename_konsep(session: Session, owner_id: str, nama_lama: str, nama_baru: str) -> dict | None:
    """Mengganti konsep pada satu Bab/SubBab tanpa mengubah unit lain yang memakai konsep lama."""
    nama_lama = nama_lama.strip()
    nama_baru = nama_baru.strip()

    def _tx(tx):
        if nama_lama == nama_baru:
            record = tx.run(
                """
                MATCH (owner)-[:HAS_KONSEP]->(k:Konsep {nama: $nama})
                WHERE (owner:Bab OR owner:SubBab) AND owner.id = $owner_id
                RETURN k.nama AS nama
                """,
                owner_id=owner_id, nama=nama_lama,
            ).single()
            return dict(record) if record else None
        record = tx.run(
            """
            MATCH (owner)-[rel:HAS_KONSEP]->(lama:Konsep {nama: $nama_lama})
            WHERE (owner:Bab OR owner:SubBab) AND owner.id = $owner_id
            MERGE (baru:Konsep {nama: $nama_baru})
            ON CREATE SET baru.deskripsi = coalesce(lama.deskripsi, '')
            MERGE (owner)-[:HAS_KONSEP]->(baru)
            DELETE rel
            WITH lama, baru
            OPTIONAL MATCH (lama)--(pemakai)
            WITH lama, baru, count(pemakai) AS jumlah_pemakai
            FOREACH (_ IN CASE WHEN jumlah_pemakai = 0 THEN [1] ELSE [] END | DELETE lama)
            RETURN baru.nama AS nama
            """,
            owner_id=owner_id, nama_lama=nama_lama, nama_baru=nama_baru,
        ).single()
        return dict(record) if record else None
    return session.execute_write(_tx)
