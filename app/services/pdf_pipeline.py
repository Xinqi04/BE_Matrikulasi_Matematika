"""Ekstraksi konsep dari modul PDF ke Neo4j.

Langkah-langkah berat (parsing PDF, deteksi struktur Bab/SubBab, ekstraksi & konsolidasi
konsep lewat LLM) didelegasikan ke engine `app.services.rekonstruksi_kg` -- lihat modul itu
untuk detail parsing/prompt. File ini cuma menjembatani hasilnya ke alur preview/confirm dan
skema Neo4j (Modul/Bab/SubBab/Konsep) yang sudah dipakai fitur lain (soal, diagnosis, dll).

Sesuai `vocabulary_policy.pdf_modul` di ontology_schema.json: jalur ini mode *ekstraksi*,
boleh membuat Konsep baru bebas dari teks.
"""

from __future__ import annotations

from typing import Callable, Optional

from google import genai
from neo4j import Session

from app.config import Settings
from app.neo4j_client import neo4j_session
from app.services import pdf_draft_store
from app.services.rekonstruksi_kg.extractor import ConceptExtractor
from app.services.rekonstruksi_kg.pdf_parser import PDFParser
from app.services.rekonstruksi_kg.rate_limiter import RateLimiter
from app.services.rekonstruksi_kg.schemas import DocumentRepresentation, ExtractionUnit, StructureUnit
from app.services.rekonstruksi_kg.structure_resolver import StructureResolver

LogFn = Callable[[str], None]


# --- Langkah 1-2: deteksi struktur (via engine rekonstruksi_kg) + susun unit ekstraksi ---

def _susun_unit_list(structure: list[StructureUnit]) -> list[dict]:
    """Konversi StructureUnit (BAB/SUBBAB, id acak dari engine rekonstruksi_kg) jadi unit_list
    bergaya lama yang dipahami kode penyimpanan Neo4j di bawah: level lowercase, nomor bab/sub
    berurutan sesuai KEMUNCULAN (bukan diparsing dari id -- id dari engine ini cuma string acak
    `unit_xxxxxxxx`, gak mengandung nomor bab/sub)."""
    unit_list: list[dict] = []
    nomor_bab = 0
    nomor_sub_per_bab: dict[str, int] = {}
    bab_str_per_engine_id: dict[str, str] = {}

    for u in structure:
        if u.level == "BAB":
            nomor_bab += 1
            bab_str = str(nomor_bab)
            bab_str_per_engine_id[u.id] = bab_str
            nomor_sub_per_bab[u.id] = 0
            unit_list.append({
                "level": "bab", "bab": bab_str, "sub": None, "judul": u.title,
                "start_page": u.start_page, "end_page": u.end_page, "summary": u.summary,
                "engine_id": u.id, "parent_engine_id": u.parent_id,
            })
        else:  # SUBBAB
            bab_str = bab_str_per_engine_id.get(u.parent_id)
            if bab_str is None:
                continue  # SubBab tanpa BAB induk (struktur cacat dari LLM) -- lewati
            nomor_sub_per_bab[u.parent_id] += 1
            sub_str = str(nomor_sub_per_bab[u.parent_id])
            unit_list.append({
                "level": "subbab", "bab": bab_str, "sub": sub_str, "judul": u.title,
                "start_page": u.start_page, "end_page": u.end_page, "summary": u.summary,
                "engine_id": u.id, "parent_engine_id": u.parent_id,
            })

    return unit_list


def susun_unit_ekstraksi(unit_list: list[dict]) -> list[dict]:
    """- BAB dengan SubBAB -> unit ekstraksi = tiap SubBAB
    - BAB tanpa SubBAB   -> unit ekstraksi = BAB itu sendiri
    """
    bab_numbers_dengan_sub = {u["bab"] for u in unit_list if u["level"] == "subbab"}
    return [u for u in unit_list if not (u["level"] == "bab" and u["bab"] in bab_numbers_dengan_sub)]


def _raw_text_unit(doc_rep: DocumentRepresentation, u: dict) -> str:
    """Ambil teks mentah halaman `start_page`..`end_page` (1-indexed, end eksklusif -- sama
    seperti konvensi StructureUnit dari engine rekonstruksi_kg)."""
    start_idx = max(0, u["start_page"] - 1)
    end_idx = min(u["end_page"], len(doc_rep.pages))
    teks = ""
    for i in range(start_idx, end_idx):
        teks += doc_rep.pages[i].text + "\n"
    return teks.strip()


# --- Langkah 3: ekstraksi konsep dengan LLM (via engine rekonstruksi_kg) ---

def _label_unit(u: dict) -> str:
    return f"BAB {u['bab']}" if u["level"] == "bab" else f"{u['bab']}.{u['sub']}"


# --- Langkah 4: simpan ke Neo4j ---

def _setup_constraints(tx):
    tx.run("CREATE CONSTRAINT modul_id IF NOT EXISTS FOR (m:Modul) REQUIRE m.id IS UNIQUE")
    tx.run("CREATE CONSTRAINT bab_id IF NOT EXISTS FOR (b:Bab) REQUIRE b.id IS UNIQUE")
    tx.run("CREATE CONSTRAINT subbab_id IF NOT EXISTS FOR (s:SubBab) REQUIRE s.id IS UNIQUE")
    tx.run("CREATE CONSTRAINT konsep_nama IF NOT EXISTS FOR (k:Konsep) REQUIRE k.nama IS UNIQUE")


def _simpan_modul(tx, modul_id: str, nama_domain: str):
    tx.run(
        "MERGE (m:Modul {id: $id}) SET m.nama_domain = $nama_domain",
        id=modul_id, nama_domain=nama_domain,
    )


def _simpan_bab(tx, modul_id: str, unit: dict) -> str:
    bab_id = f"{modul_id}_bab{unit['bab']}"
    tx.run(
        """
        MERGE (b:Bab {id: $bab_id})
        SET b.nama = $nama, b.nomor = $nomor
        WITH b
        MATCH (m:Modul {id: $modul_id})
        MERGE (m)-[:HAS_BAB]->(b)
        """,
        bab_id=bab_id, nama=unit["judul"], nomor=unit["bab"], modul_id=modul_id,
    )
    return bab_id


def _simpan_subbab(tx, modul_id: str, unit: dict) -> str:
    bab_id = f"{modul_id}_bab{unit['bab']}"
    sub_id = f"{modul_id}_bab{unit['bab']}_sub{unit['sub']}"
    tx.run(
        """
        MERGE (s:SubBab {id: $sub_id})
        SET s.nama = $nama, s.nomor = $nomor
        WITH s
        MATCH (b:Bab {id: $bab_id})
        MERGE (b)-[:HAS_SUBBAB]->(s)
        """,
        sub_id=sub_id, nama=unit["judul"], nomor=f"{unit['bab']}.{unit['sub']}", bab_id=bab_id,
    )
    return sub_id


def _hitung_unit_id(modul_id: str, unit: dict) -> str:
    if unit["level"] == "bab":
        return f"{modul_id}_bab{unit['bab']}"
    return f"{modul_id}_bab{unit['bab']}_sub{unit['sub']}"


def _simpan_konsep(tx, unit_id: str, konsep_list: list[dict]):
    for konsep in konsep_list:
        nama_bersih = konsep["nama"].strip().lower()
        deskripsi = (konsep.get("deskripsi") or "").strip()
        tx.run(
            """
            MERGE (k:Konsep {nama: $nama})
            SET k.deskripsi = CASE WHEN $deskripsi <> '' THEN $deskripsi ELSE k.deskripsi END
            WITH k
            MATCH (u {id: $unit_id})
            MERGE (u)-[:HAS_KONSEP]->(k)
            """,
            nama=nama_bersih, deskripsi=deskripsi, unit_id=unit_id,
        )


def simpan_struktur_dan_konsep(
    session: Session, modul_id: str, nama_domain: str,
    unit_list: list[dict], unit_final: list[dict], log: LogFn,
):
    session.execute_write(_setup_constraints)
    session.execute_write(_simpan_modul, modul_id, nama_domain)

    # Struktur (Bab/SubBab) disimpan dari unit_list LENGKAP (bukan unit_final) -- unit_final
    # sudah membuang entry "bab" yang punya SubBab (teksnya dicakup di level SubBab), jadi kalau
    # dipakai untuk struktur, Bab yang punya SubBab kehilangan judul aslinya.
    jumlah_bab, jumlah_subbab = 0, 0
    for u in unit_list:
        if u["level"] == "bab":
            session.execute_write(_simpan_bab, modul_id, u)
            jumlah_bab += 1
        else:
            session.execute_write(_simpan_subbab, modul_id, u)
            jumlah_subbab += 1
    log(f"Struktur graph tersimpan: {jumlah_bab} node :Bab, {jumlah_subbab} node :SubBab.")

    total_konsep = 0
    for u in unit_final:
        unit_id = _hitung_unit_id(modul_id, u)
        konsep_list = u.get("hasil_konsep", [])
        session.execute_write(_simpan_konsep, unit_id, konsep_list)
        total_konsep += len(konsep_list)
        log(f"Konsep ditempel: {_label_unit(u)} - {len(konsep_list)} konsep")

    return total_konsep


# --- Orkestrasi end-to-end ---
#
# Alur dipecah jadi dua tahap biar dosen bisa REVIEW hasil ekstraksi LLM (hapus konsep yang
# gak sesuai, tambah konsep manual) SEBELUM apa pun ditulis ke Neo4j:
#
#   1. `run_pdf_extraction_preview` -- dipanggil dari job background. Parsing PDF, deteksi
#      struktur, dan ekstrak konsep lewat engine rekonstruksi_kg, TAPI belum nyentuh Neo4j sama
#      sekali. Hasil lengkap (`unit_list` + `unit_final`) disimpen di `pdf_draft_store` (keyed
#      by job_id), sementara ringkasannya (buat ditampilin di UI) jadi `job.result`.
#   2. `confirm_pdf_extraction` -- dipanggil pas dosen klik "Simpan". Ambil draft dari cache,
#      timpa `hasil_konsep` tiap unit sesuai editan dosen, baru panggil `simpan_struktur_dan_konsep`.
#
# Kalau dosen gak jadi simpan, `discard_pdf_draft` cukup buang draft dari cache -- gak ada
# jejak apa pun di Neo4j.


def _ringkasan_unit(modul_id: str, unit_final: list[dict]) -> list[dict]:
    return [
        {
            "unit_id": _hitung_unit_id(modul_id, u),
            "level": u["level"],
            "label": _label_unit(u),
            "judul": u["judul"],
            "konsep": u.get("hasil_konsep", []),
        }
        for u in unit_final
    ]


def run_pdf_extraction_preview(
    job_id: str, pdf_path: str, modul_id: str, nama_domain: Optional[str], settings: Settings, log: LogFn,
) -> dict:
    """Parsing PDF + deteksi struktur + ekstraksi konsep (lewat engine rekonstruksi_kg) TANPA
    nulis apa pun ke Neo4j. Hasil lengkap disimpen di `pdf_draft_store` supaya bisa
    dikonfirmasi/dikoreksi lewat `confirm_pdf_extraction`."""

    nama_domain = nama_domain or settings.default_nama_domain
    client = genai.Client(api_key=settings.gemini_api_key)

    log(f"Membaca dan mem-parsing PDF: {pdf_path}")
    parser = PDFParser(pdf_path)
    try:
        doc_rep = parser.extract_document()
    finally:
        parser.close()
    log(f"PDF berhasil dibaca ({len(doc_rep.pages)} halaman).")

    log("Menyusun struktur dokumen (BAB/SubBab)...")
    structure = StructureResolver(doc_rep, client, settings.gemini_structure_model).resolve()
    if not structure:
        raise NotImplementedError(
            "Struktur dokumen gak berhasil dideteksi (bookmark PDF, Daftar Isi, maupun LLM gagal)."
        )
    unit_list = _susun_unit_list(structure)
    jumlah_bab = sum(1 for u in unit_list if u["level"] == "bab")
    jumlah_subbab = sum(1 for u in unit_list if u["level"] == "subbab")
    log(f"Struktur terdeteksi: {jumlah_bab} BAB, {jumlah_subbab} SubBAB.")

    unit_final = susun_unit_ekstraksi(unit_list)
    log(f"Total unit final untuk diekstraksi: {len(unit_final)}")

    extraction_units = [
        ExtractionUnit(
            unit_id=u["engine_id"], level=u["level"].upper(), title=u["judul"],
            parent_id=u["parent_engine_id"], summary=u["summary"],
            start_page=u["start_page"], end_page=u["end_page"],
            raw_text=_raw_text_unit(doc_rep, u),
        )
        for u in unit_final
    ]

    def _on_progress(current: int, total: int, title: str) -> None:
        log(f"Ekstraksi unit {current}/{total}: {title}")

    extractor = ConceptExtractor(
        client, settings.gemini_extraction_model,
        RateLimiter(settings.llm_request_delay_seconds, settings.llm_max_retries),
        settings.max_unit_tokens,
    )
    extractions, errors = extractor.extract_sequential(extraction_units, on_progress=_on_progress)
    for err in errors:
        log(f"  [{err.unit_id}] GAGAL ekstraksi: {err.error}")

    log("Konsolidasi hasil ekstraksi antar unit...")
    extractions = extractor.consolidate(extractions, extraction_units)

    konsep_per_engine_id = {ext.unit_id: ext.konsep for ext in extractions}
    for u in unit_final:
        konsep_list = konsep_per_engine_id.get(u["engine_id"], [])
        u["hasil_konsep"] = [{"nama": k.nama, "deskripsi": k.deskripsi} for k in konsep_list]
        log(f"  -> {_label_unit(u)} - {u['judul']}: {len(u['hasil_konsep'])} konsep final")

    pdf_draft_store.save_draft(job_id, {
        "modul_id": modul_id, "nama_domain": nama_domain, "unit_list": unit_list, "unit_final": unit_final,
    })
    log("Ekstraksi selesai -- menunggu konfirmasi dosen sebelum disimpan ke Knowledge Graph.")

    unit_ringkas = _ringkasan_unit(modul_id, unit_final)
    return {
        "modul_id": modul_id,
        "nama_domain": nama_domain,
        "jumlah_unit": len(unit_final),
        "jumlah_konsep_total": sum(len(u["konsep"]) for u in unit_ringkas),
        "status_penyimpanan": "menunggu_konfirmasi",
        "unit": unit_ringkas,
    }


def confirm_pdf_extraction(job_id: str, konsep_overrides: dict[str, list[dict]]) -> Optional[dict]:
    """Timpa `hasil_konsep` tiap unit sesuai editan dosen (`konsep_overrides`: unit_id -> daftar
    konsep final `{"nama": ..., "deskripsi": ...}`), lalu tulis struktur + konsep ke Neo4j.
    Return None kalau draft-nya gak ada (job_id salah, atau sudah dikonfirmasi/dibuang
    sebelumnya)."""

    draft = pdf_draft_store.pop_draft(job_id)
    if draft is None:
        return None

    modul_id, nama_domain = draft["modul_id"], draft["nama_domain"]
    unit_list, unit_final = draft["unit_list"], draft["unit_final"]

    for u in unit_final:
        unit_id = _hitung_unit_id(modul_id, u)
        if unit_id in konsep_overrides:
            u["hasil_konsep"] = [
                {"nama": k["nama"].strip(), "deskripsi": (k.get("deskripsi") or "").strip()}
                for k in konsep_overrides[unit_id] if k.get("nama", "").strip()
            ]

    with neo4j_session() as session:
        total_konsep = simpan_struktur_dan_konsep(session, modul_id, nama_domain, unit_list, unit_final, log=lambda _msg: None)

    return {
        "detail": "Struktur & konsep berhasil disimpan ke Knowledge Graph.",
        "jumlah_konsep_total": total_konsep,
        "unit": _ringkasan_unit(modul_id, unit_final),
    }


def discard_pdf_draft(job_id: str) -> bool:
    """Buang draft ekstraksi tanpa nulis apa pun ke Neo4j. Return False kalau draft-nya udah gak ada."""
    return pdf_draft_store.pop_draft(job_id) is not None


# --- Hapus modul ---

def hapus_modul(session: Session, modul_id: str) -> Optional[dict]:
    """Hapus Modul beserta semua Bab/SubBab/Soal di bawahnya (dan otomatis semua relationship yang
    nempel -- HAS_KONSEP, MENGUJI, MENJAWAB, MENGAMBIL -- lewat DETACH DELETE). Node `:Konsep`
    SENGAJA gak ikut dihapus karena itu vocabulary bersama, bisa dipakai modul lain atau Materi
    video -- kalau jadi yatim piatu (gak ada relasi apapun lagi) ya biarin, gak masalah. Return None
    kalau modul_id gak ketemu."""

    def _hitung(tx):
        result = tx.run(
            """
            MATCH (m:Modul {id: $modul_id})
            OPTIONAL MATCH (m)-[:HAS_BAB]->(b:Bab)
            OPTIONAL MATCH (b)-[:HAS_SUBBAB]->(sub:SubBab)
            OPTIONAL MATCH (b)-[:HAS_SOAL]->(s:Soal)
            OPTIONAL MATCH (s)<-[j:MENJAWAB]-(:User)
            RETURN m.nama_domain AS nama_domain, count(DISTINCT b) AS jumlah_bab,
                   count(DISTINCT sub) AS jumlah_subbab, count(DISTINCT s) AS jumlah_soal,
                   count(DISTINCT j) AS jumlah_jawaban
            """,
            modul_id=modul_id,
        )
        record = result.single()
        return dict(record) if record and record["nama_domain"] is not None else None

    ringkasan = session.execute_read(_hitung)
    if ringkasan is None:
        return None

    def _hapus(tx):
        tx.run(
            """
            MATCH (m:Modul {id: $modul_id})
            OPTIONAL MATCH (m)-[:HAS_BAB]->(b:Bab)
            OPTIONAL MATCH (b)-[:HAS_SUBBAB]->(sub:SubBab)
            OPTIONAL MATCH (b)-[:HAS_SOAL]->(s:Soal)
            DETACH DELETE m, b, sub, s
            """,
            modul_id=modul_id,
        )

    session.execute_write(_hapus)
    return ringkasan
