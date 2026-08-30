"""Jawaban mahasiswa disimpan sebagai relationship properties `(User)-[:MENJAWAB]->(Soal)`
(bukan node terpisah). Tidak ada perhitungan nilai otomatis di sini -- nilai murni input manual dosen.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Optional

from neo4j import Session

STATUS_MENUNGGU = "menunggu_penilaian"
STATUS_DINILAI = "dinilai"


def submit_jawaban(session: Session, mahasiswa_id: str, bab_id: str, daftar_jawaban: list[dict]) -> list[dict]:
    """`daftar_jawaban`: list of {"soal_id": ..., "teks_jawaban": ...}. Soal yang bukan milik `bab_id`
    diabaikan (safety -- mahasiswa hanya boleh menjawab soal dari Bab yang sedang dikerjakan)."""

    def _tx(tx):
        hasil = []
        for item in daftar_jawaban:
            result = tx.run(
                """
                MATCH (b:Bab {id: $bab_id})-[:HAS_SOAL]->(s:Soal {id: $soal_id})
                MATCH (u:User {id: $mahasiswa_id})
                MERGE (u)-[r:MENJAWAB]->(s)
                ON CREATE SET r.id = $new_id
                SET r.teks_jawaban = $teks_jawaban, r.status = $status, r.nilai = null,
                    r.dijawab_pada = $dijawab_pada, r.dinilai_pada = null
                RETURN r.id AS id, s.id AS soal_id
                """,
                bab_id=bab_id, soal_id=item["soal_id"], mahasiswa_id=mahasiswa_id,
                new_id=str(uuid.uuid4()), teks_jawaban=item["teks_jawaban"], status=STATUS_MENUNGGU,
                dijawab_pada=datetime.now(timezone.utc).isoformat(),
            )
            record = result.single()
            if record is not None:
                hasil.append({"id": record["id"], "soal_id": record["soal_id"]})
        return hasil

    return session.execute_write(_tx)


def list_jawaban(
    session: Session, bab_id: Optional[str] = None, status: Optional[str] = None,
    mahasiswa_id: Optional[str] = None,
) -> list[dict]:
    def _tx(tx):
        result = tx.run(
            """
            MATCH (b:Bab)-[:HAS_SOAL]->(s:Soal)<-[r:MENJAWAB]-(u:User)
            WHERE ($bab_id IS NULL OR b.id = $bab_id)
              AND ($status IS NULL OR r.status = $status)
              AND ($mahasiswa_id IS NULL OR u.id = $mahasiswa_id)
            RETURN DISTINCT r.id AS id, b.id AS bab_id, u.id AS mahasiswa_id, u.nama AS mahasiswa_nama,
                   s.id AS soal_id, s.teks_soal AS teks_soal, s.tipe AS tipe,
                   s.jawaban_referensi AS jawaban_referensi, r.teks_jawaban AS teks_jawaban,
                   r.nilai AS nilai, r.status AS status, r.dijawab_pada AS dijawab_pada,
                   r.dinilai_pada AS dinilai_pada
            ORDER BY r.dijawab_pada
            """,
            bab_id=bab_id, status=status, mahasiswa_id=mahasiswa_id,
        )
        return [dict(r) for r in result]

    return session.execute_read(_tx)


def beri_nilai(session: Session, jawaban_id: str, nilai: float) -> Optional[dict]:
    def _tx(tx):
        result = tx.run(
            """
            MATCH ()-[r:MENJAWAB {id: $jawaban_id}]->()
            SET r.nilai = $nilai, r.status = $status, r.dinilai_pada = $dinilai_pada
            RETURN r.id AS id, r.nilai AS nilai, r.status AS status
            """,
            jawaban_id=jawaban_id, nilai=nilai, status=STATUS_DINILAI,
            dinilai_pada=datetime.now(timezone.utc).isoformat(),
        )
        record = result.single()
        return dict(record) if record else None

    return session.execute_write(_tx)


def beri_nilai_batch(session: Session, daftar_nilai: list[dict]) -> list[dict]:
    """`daftar_nilai`: list of {"jawaban_id": ..., "nilai": ...}. `jawaban_id` yang gak match
    (mis. sudah dihapus/berubah sejak halaman terakhir dimuat) di-skip, bukan gagal total --
    item lain di batch yang sama tetap tersimpan."""

    def _tx(tx):
        hasil = []
        for item in daftar_nilai:
            result = tx.run(
                """
                MATCH ()-[r:MENJAWAB {id: $jawaban_id}]->()
                SET r.nilai = $nilai, r.status = $status, r.dinilai_pada = $dinilai_pada
                RETURN r.id AS id, r.nilai AS nilai, r.status AS status
                """,
                jawaban_id=item["jawaban_id"], nilai=item["nilai"], status=STATUS_DINILAI,
                dinilai_pada=datetime.now(timezone.utc).isoformat(),
            )
            record = result.single()
            if record is not None:
                hasil.append(dict(record))
        return hasil

    return session.execute_write(_tx)
