"""Manajemen `:Soal` per Bab, termasuk saran konsep lewat LLM (closed vocabulary, pola sama seperti
`youtube_pipeline.klasifikasi_video_llm` -- LLM cuma boleh milih dari konsep yang sudah ada di Bab itu,
dosen yang mengonfirmasi sebelum `:Soal` benar-benar dibuat).
"""

from __future__ import annotations

import json
import re
import time
import uuid
from datetime import datetime, timezone
from typing import Optional

from google import genai
from neo4j import Session

from app.config import Settings


def konsep_kandidat(session: Session, bab_id: str) -> list[str]:
    """Daftar Konsep "milik" sebuah Bab. `HAS_KONSEP` cuma nempel di unit leaf (lihat pdf_pipeline.py):
    kalau Bab itu punya SubBab, konsepnya ada di tiap SubBab, bukan di Bab langsung."""

    def _tx(tx):
        result = tx.run(
            """
            MATCH (b:Bab {id: $bab_id})
            OPTIONAL MATCH (b)-[:HAS_SUBBAB]->(sub:SubBab)
            OPTIONAL MATCH (b)-[:HAS_KONSEP]->(kb:Konsep)
            OPTIONAL MATCH (sub)-[:HAS_KONSEP]->(ks:Konsep)
            RETURN collect(DISTINCT kb.nama) AS konsep_bab, collect(DISTINCT ks.nama) AS konsep_sub
            """,
            bab_id=bab_id,
        )
        record = result.single()
        if record is None:
            return []
        konsep_sub = [k for k in record["konsep_sub"] if k is not None]
        konsep_bab = [k for k in record["konsep_bab"] if k is not None]
        return sorted(konsep_sub) if konsep_sub else sorted(konsep_bab)

    return session.execute_read(_tx)


def konsep_kandidat_detail(session: Session, bab_id: str) -> list[dict]:
    """Sama seperti `konsep_kandidat` (leaf-only: SubBab kalau ada, kalau tidak Bab langsung), tapi
    balikin `{"nama": ..., "deskripsi": ...}` per konsep -- dipakai generator soal LLM biar punya
    konteks definisi konsep, bukan cuma nama doang."""

    def _tx(tx):
        result = tx.run(
            """
            MATCH (b:Bab {id: $bab_id})
            OPTIONAL MATCH (b)-[:HAS_SUBBAB]->(sub:SubBab)
            OPTIONAL MATCH (b)-[:HAS_KONSEP]->(kb:Konsep)
            OPTIONAL MATCH (sub)-[:HAS_KONSEP]->(ks:Konsep)
            RETURN collect(DISTINCT {nama: kb.nama, deskripsi: kb.deskripsi}) AS konsep_bab,
                   collect(DISTINCT {nama: ks.nama, deskripsi: ks.deskripsi}) AS konsep_sub
            """,
            bab_id=bab_id,
        )
        record = result.single()
        if record is None:
            return []
        konsep_sub = [k for k in record["konsep_sub"] if k["nama"] is not None]
        konsep_bab = [k for k in record["konsep_bab"] if k["nama"] is not None]
        dipakai = konsep_sub if konsep_sub else konsep_bab
        return sorted(dipakai, key=lambda k: k["nama"])

    return session.execute_read(_tx)


def get_bab_info(session: Session, bab_id: str) -> Optional[dict]:
    """Ringkasan Bab (nomor, nama, summary Bab + SubBab-nya kalau ada) -- konteks buat prompt
    generator soal LLM."""

    def _tx(tx):
        result = tx.run(
            """
            MATCH (b:Bab {id: $bab_id})
            OPTIONAL MATCH (b)-[:HAS_SUBBAB]->(sub:SubBab)
            RETURN b.nomor AS nomor, b.nama AS nama, b.summary AS summary,
                   collect(DISTINCT sub.summary) AS subbab_summary
            """,
            bab_id=bab_id,
        )
        record = result.single()
        if record is None or record["nama"] is None:
            return None
        subbab_summary = [s for s in record["subbab_summary"] if s]
        return {
            "nomor": record["nomor"], "nama": record["nama"],
            "summary": record["summary"] or "", "subbab_summary": subbab_summary,
        }

    return session.execute_read(_tx)


_PROMPT_SARAN_KONSEP = """Kamu adalah asisten yang membantu dosen menandai konsep apa saja yang diuji oleh
sebuah soal ujian matematika.

Teks soal:
\"\"\"
{teks_soal}
\"\"\"

Berikut daftar KONSEP yang ada di Bab yang sama. Kamu HANYA boleh memilih dari daftar ini -- SALIN PERSIS
penulisannya, jangan diparafrase, dan DILARANG membuat nama konsep baru di luar daftar:
{daftar_konsep}

Tugas: tentukan konsep MANAPUN dari daftar yang benar-benar diuji/dibutuhkan untuk menjawab soal ini
(boleh lebih dari satu). Kalau tidak ada satupun yang cocok, kembalikan list kosong.

Balas HANYA dengan JSON valid, tanpa teks lain, tanpa markdown code fence, format:
{{"konsep_terpilih": ["nama konsep -- SALIN PERSIS dari daftar", "..."]}}
"""


def _clean_json_response(raw: str) -> str:
    return re.sub(r"^```(json)?|```$", "", raw.strip(), flags=re.MULTILINE).strip()


def sarankan_konsep_llm(
    settings: Settings, teks_soal: str, daftar_konsep: list[str], max_retry: int = 2,
) -> list[str]:
    if not daftar_konsep:
        return []

    client = genai.Client(api_key=settings.gemini_api_key)
    prompt = _PROMPT_SARAN_KONSEP.format(
        teks_soal=teks_soal, daftar_konsep="\n".join(f"- {k}" for k in daftar_konsep),
    )

    for percobaan in range(max_retry):
        try:
            response = client.models.generate_content(model=settings.gemini_model, contents=prompt)
            data = json.loads(_clean_json_response(response.text))
            hasil = data.get("konsep_terpilih", [])
            daftar_lower = {k.lower(): k for k in daftar_konsep}
            return [daftar_lower[h.lower()] for h in hasil if h.lower() in daftar_lower]
        except json.JSONDecodeError:
            time.sleep(1)
        except Exception:  # noqa: BLE001 - saran LLM opsional, dosen tetap bisa pilih manual kalau gagal
            time.sleep(1)

    return []


def _setup_constraint(tx):
    tx.run("CREATE CONSTRAINT soal_id IF NOT EXISTS FOR (s:Soal) REQUIRE s.id IS UNIQUE")


def buat_soal(
    session: Session, bab_id: str, teks_soal: str, tipe: str, konsep_list: list[str],
    dibuat_oleh: str, jawaban_referensi: Optional[str] = None, tingkat_kesulitan: Optional[str] = None,
) -> dict:
    # Neo4j gak boleh nyampur schema modification (CREATE CONSTRAINT) sama data write dalam satu
    # transaksi yang sama -- makanya dipisah jadi write terpisah, sama kayak pola di pdf_pipeline.py.
    session.execute_write(_setup_constraint)

    def _tx(tx):
        soal_id = str(uuid.uuid4())
        tx.run(
            """
            MATCH (b:Bab {id: $bab_id})
            CREATE (s:Soal {
                id: $soal_id, teks_soal: $teks_soal, tipe: $tipe,
                jawaban_referensi: $jawaban_referensi, tingkat_kesulitan: $tingkat_kesulitan,
                dibuat_oleh: $dibuat_oleh, dibuat_pada: $dibuat_pada
            })
            MERGE (b)-[:HAS_SOAL]->(s)
            """,
            bab_id=bab_id, soal_id=soal_id, teks_soal=teks_soal, tipe=tipe,
            jawaban_referensi=jawaban_referensi, tingkat_kesulitan=tingkat_kesulitan,
            dibuat_oleh=dibuat_oleh, dibuat_pada=datetime.now(timezone.utc).isoformat(),
        )
        for nama_konsep in konsep_list:
            tx.run(
                """
                MATCH (s:Soal {id: $soal_id})
                MATCH (k:Konsep {nama: $nama})
                MERGE (s)-[:MENGUJI]->(k)
                """,
                soal_id=soal_id, nama=nama_konsep.strip().lower(),
            )
        return soal_id

    soal_id = session.execute_write(_tx)
    return get_soal(session, soal_id)


def update_soal(
    session: Session, soal_id: str, teks_soal: str, tipe: str, konsep_list: list[str],
    jawaban_referensi: Optional[str] = None, tingkat_kesulitan: Optional[str] = None,
) -> Optional[dict]:
    def _tx(tx):
        result = tx.run(
            """
            MATCH (s:Soal {id: $soal_id})
            SET s.teks_soal = $teks_soal, s.tipe = $tipe,
                s.jawaban_referensi = $jawaban_referensi, s.tingkat_kesulitan = $tingkat_kesulitan
            WITH s
            OPTIONAL MATCH (s)-[r:MENGUJI]->(:Konsep)
            DELETE r
            RETURN s.id AS id
            """,
            soal_id=soal_id, teks_soal=teks_soal, tipe=tipe,
            jawaban_referensi=jawaban_referensi, tingkat_kesulitan=tingkat_kesulitan,
        )
        if result.single() is None:
            return False
        for nama_konsep in konsep_list:
            tx.run(
                """
                MATCH (s:Soal {id: $soal_id})
                MATCH (k:Konsep {nama: $nama})
                MERGE (s)-[:MENGUJI]->(k)
                """,
                soal_id=soal_id, nama=nama_konsep.strip().lower(),
            )
        return True

    ditemukan = session.execute_write(_tx)
    return get_soal(session, soal_id) if ditemukan else None


def get_soal(session: Session, soal_id: str) -> Optional[dict]:
    def _tx(tx):
        result = tx.run(
            """
            MATCH (b:Bab)-[:HAS_SOAL]->(s:Soal {id: $soal_id})
            OPTIONAL MATCH (s)-[:MENGUJI]->(k:Konsep)
            RETURN s, b.id AS bab_id, collect(k.nama) AS konsep
            """,
            soal_id=soal_id,
        )
        record = result.single()
        if record is None:
            return None
        data = dict(record["s"])
        data["bab_id"] = record["bab_id"]
        data["konsep"] = record["konsep"]
        return data

    return session.execute_read(_tx)


def list_soal(session: Session, bab_id: str) -> list[dict]:
    def _tx(tx):
        result = tx.run(
            """
            MATCH (b:Bab {id: $bab_id})-[:HAS_SOAL]->(s:Soal)
            OPTIONAL MATCH (s)-[:MENGUJI]->(k:Konsep)
            RETURN s, b.id AS bab_id, collect(k.nama) AS konsep
            ORDER BY s.dibuat_pada
            """,
            bab_id=bab_id,
        )
        rows = []
        for r in result:
            data = dict(r["s"])
            data["bab_id"] = r["bab_id"]
            data["konsep"] = r["konsep"]
            rows.append(data)
        return rows

    return session.execute_read(_tx)


def hapus_soal(session: Session, soal_id: str) -> None:
    def _tx(tx):
        tx.run("MATCH (s:Soal {id: $soal_id}) DETACH DELETE s", soal_id=soal_id)

    session.execute_write(_tx)
