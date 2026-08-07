"""Diagnosis nilai per Bab (remedial/pengayaan/lanjut) + rekomendasi video lewat content-based
filtering: Jaccard similarity antara himpunan nama konsep target dan himpunan nama konsep tiap materi
(`Materi-[:MEMBAHAS_KONSEP]->Konsep`, hasil pipeline klasifikasi YouTube yang sudah ada -- `Materi` adalah
node generik, bisa nampung sumber selain YouTube nantinya lewat properti `tipe`).

Aturan (sesuai spesifikasi):
- nilai_bab < 70                              -> remedial, fokus = konsep dengan nilai < 70 di Bab itu
- nilai_bab >= 70 tapi ada konsep < 70         -> pengayaan, fokus = konsep-konsep < 70 itu
- nilai_bab >= 70 dan semua konsep >= 70       -> lanjut, fokus = konsep-konsep Bab berikutnya
"""

from __future__ import annotations

from typing import Optional

from neo4j import Session

from app.services.jawaban_repo import STATUS_DINILAI
from app.services.soal_pipeline import konsep_kandidat

BATAS_LULUS = 70


def nilai_bab_mahasiswa(session: Session, mahasiswa_id: str, bab_id: str) -> Optional[float]:
    def _tx(tx):
        result = tx.run(
            """
            MATCH (b:Bab {id: $bab_id})-[:HAS_SOAL]->(s:Soal)<-[r:MENJAWAB {status: $status}]-(u:User {id: $mahasiswa_id})
            RETURN avg(r.nilai) AS nilai_bab, count(r) AS jumlah
            """,
            bab_id=bab_id, mahasiswa_id=mahasiswa_id, status=STATUS_DINILAI,
        )
        record = result.single()
        if record is None or record["jumlah"] == 0:
            return None
        return float(record["nilai_bab"])

    return session.execute_read(_tx)


def _nilai_per_konsep(session: Session, mahasiswa_id: str, bab_id: str) -> dict[str, float]:
    def _tx(tx):
        result = tx.run(
            """
            MATCH (b:Bab {id: $bab_id})-[:HAS_SOAL]->(s:Soal)-[:MENGUJI]->(k:Konsep)
            MATCH (s)<-[r:MENJAWAB {status: $status}]-(u:User {id: $mahasiswa_id})
            RETURN k.nama AS konsep, avg(r.nilai) AS nilai
            """,
            bab_id=bab_id, mahasiswa_id=mahasiswa_id, status=STATUS_DINILAI,
        )
        return {r["konsep"]: float(r["nilai"]) for r in result}

    return session.execute_read(_tx)


def _cari_bab_berikutnya(session: Session, bab_id: str) -> Optional[dict]:
    def _tx(tx):
        result = tx.run(
            """
            MATCH (m:Modul)-[:HAS_BAB]->(bab:Bab {id: $bab_id})
            MATCH (m)-[:HAS_BAB]->(next:Bab)
            WHERE toInteger(next.nomor) = toInteger(bab.nomor) + 1
            RETURN next.id AS id, next.nomor AS nomor, next.nama AS nama
            LIMIT 1
            """,
            bab_id=bab_id,
        )
        record = result.single()
        return dict(record) if record else None

    return session.execute_read(_tx)


def _cari_bab_sebelumnya(session: Session, bab_id: str) -> Optional[dict]:
    def _tx(tx):
        result = tx.run(
            """
            MATCH (m:Modul)-[:HAS_BAB]->(bab:Bab {id: $bab_id})
            MATCH (m)-[:HAS_BAB]->(prev:Bab)
            WHERE toInteger(prev.nomor) = toInteger(bab.nomor) - 1
            RETURN prev.id AS id, prev.nomor AS nomor, prev.nama AS nama
            LIMIT 1
            """,
            bab_id=bab_id,
        )
        record = result.single()
        return dict(record) if record else None

    return session.execute_read(_tx)


def status_bab(session: Session, mahasiswa_id: str, bab_id: str) -> tuple[str, Optional[float]]:
    """Versi ringan `diagnosa_bab` buat dashboard/daftar Bab -- cuma butuh status + nilai, tanpa
    query rekomendasi video & konsep Bab berikutnya (mahal kalau dipanggil per-Bab di satu daftar)."""
    nilai_bab = nilai_bab_mahasiswa(session, mahasiswa_id, bab_id)
    if nilai_bab is None:
        return "belum_ada_nilai", None

    nilai_per_konsep = _nilai_per_konsep(session, mahasiswa_id, bab_id)
    konsep_lemah = [k for k, v in nilai_per_konsep.items() if v < BATAS_LULUS]

    if nilai_bab < BATAS_LULUS:
        return "remedial", nilai_bab
    if konsep_lemah:
        return "pengayaan", nilai_bab
    return "lanjut", nilai_bab


def bab_terkunci(session: Session, mahasiswa_id: str, bab_id: str) -> bool:
    """Bab tanpa Bab sebelumnya dalam Modul yang sama (nomor terkecil) selalu terbuka. Bab lain
    terkunci sampai Bab sebelumnya lulus (nilai >= BATAS_LULUS); remedial (dinilai tapi <
    BATAS_LULUS) atau belum dinilai sama sekali tetap terkunci."""
    bab_sebelumnya = _cari_bab_sebelumnya(session, bab_id)
    if bab_sebelumnya is None:
        return False
    nilai_sebelumnya = nilai_bab_mahasiswa(session, mahasiswa_id, bab_sebelumnya["id"])
    return nilai_sebelumnya is None or nilai_sebelumnya < BATAS_LULUS


def rekomendasi_video_cbf(session: Session, himpunan_target: set[str], top_n: int = 5) -> list[dict]:
    if not himpunan_target:
        return []

    def _tx(tx):
        result = tx.run(
            """
            MATCH (v:Materi)
            OPTIONAL MATCH (v)-[:MEMBAHAS_KONSEP]->(k:Konsep)
            RETURN v.id AS video_id, v.judul AS judul, v.sumber AS link, v.kontributor AS channel,
                   v.thumbnail AS thumbnail, collect(k.nama) AS konsep
            """
        )
        return [dict(r) for r in result]

    videos = session.execute_read(_tx)

    hasil = []
    for v in videos:
        himpunan_video = set(v["konsep"]) - {None}
        if not himpunan_video:
            continue
        irisan = himpunan_target & himpunan_video
        gabungan = himpunan_target | himpunan_video
        similarity = len(irisan) / len(gabungan) if gabungan else 0.0
        if similarity > 0:
            hasil.append({
                "video_id": v["video_id"], "judul": v["judul"], "link": v["link"], "channel": v["channel"],
                "thumbnail": v["thumbnail"], "jaccard": round(similarity, 3), "konsep_cocok": sorted(irisan),
            })

    hasil.sort(key=lambda x: x["jaccard"], reverse=True)
    return hasil[:top_n]


def diagnosa_bab(session: Session, mahasiswa_id: str, bab_id: str, top_n_video: int = 5) -> dict:
    nilai_bab = nilai_bab_mahasiswa(session, mahasiswa_id, bab_id)
    if nilai_bab is None:
        return {
            "status": "belum_ada_nilai", "nilai_bab": None, "nilai_per_konsep": {},
            "konsep_fokus": [], "rekomendasi_video": [],
        }

    nilai_per_konsep = _nilai_per_konsep(session, mahasiswa_id, bab_id)
    konsep_lemah = sorted(k for k, v in nilai_per_konsep.items() if v < BATAS_LULUS)

    if nilai_bab < BATAS_LULUS:
        status = "remedial"
        konsep_fokus = konsep_lemah or sorted(nilai_per_konsep.keys())
    elif konsep_lemah:
        status = "pengayaan"
        konsep_fokus = konsep_lemah
    else:
        status = "lanjut"
        bab_berikutnya = _cari_bab_berikutnya(session, bab_id)
        konsep_fokus = konsep_kandidat(session, bab_berikutnya["id"]) if bab_berikutnya else []

    rekomendasi_video = rekomendasi_video_cbf(session, set(konsep_fokus), top_n_video) if konsep_fokus else []

    return {
        "status": status,
        "nilai_bab": round(nilai_bab, 2),
        "nilai_per_konsep": {k: round(v, 2) for k, v in nilai_per_konsep.items()},
        "konsep_fokus": konsep_fokus,
        "rekomendasi_video": rekomendasi_video,
    }
