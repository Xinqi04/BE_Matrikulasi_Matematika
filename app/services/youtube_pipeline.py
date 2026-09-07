"""Klasifikasi video YouTube ke Konsep yang sudah ada di Neo4j (closed vocabulary).

Port dari `pipeline_klasifikasi_youtube_kg.ipynb`, diadaptasi untuk klasifikasi satu link
YouTube per request (bukan batch CSV). Sesuai `vocabulary_policy.youtube` di
ontology_schema.json: jalur ini mode *klasifikasi*, LLM di sini TIDAK boleh membuat Konsep
baru, cuma boleh memilih dari daftar Konsep yang sudah ada.
"""

from __future__ import annotations

import json
import re
import time
from typing import Callable, Optional
from urllib.parse import parse_qs, urlparse

from google import genai
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from neo4j import Session

from app.config import Settings
from app.neo4j_client import neo4j_session
from app.services import youtube_draft_store

LogFn = Callable[[str], None]


class YoutubeLinkError(ValueError):
    pass


class VideoNotFoundError(ValueError):
    pass


def extract_video_id(link: str) -> str:
    """Terima berbagai bentuk link YouTube (watch?v=, youtu.be/, embed/, shorts/) atau video_id polos."""
    link = link.strip()
    if re.fullmatch(r"[A-Za-z0-9_-]{11}", link):
        return link

    parsed = urlparse(link)
    host = (parsed.hostname or "").lower()

    if host in ("youtu.be",):
        video_id = parsed.path.lstrip("/")
        if video_id:
            return video_id

    if "youtube.com" in host or "youtube-nocookie.com" in host:
        qs = parse_qs(parsed.query)
        if "v" in qs and qs["v"]:
            return qs["v"][0]
        m = re.search(r"/(?:embed|shorts)/([A-Za-z0-9_-]{11})", parsed.path)
        if m:
            return m.group(1)

    raise YoutubeLinkError(f"Tidak bisa mengekstrak video_id dari link: {link}")


def fetch_video_snippet(video_id: str, youtube_api_key: str) -> dict:
    youtube = build("youtube", "v3", developerKey=youtube_api_key)
    try:
        response = youtube.videos().list(part="snippet", id=video_id).execute()
    except HttpError as err:
        raise VideoNotFoundError(f"Gagal mengambil detail video '{video_id}': {err}") from err

    items = response.get("items", [])
    if not items:
        raise VideoNotFoundError(f"Video '{video_id}' tidak ditemukan (mungkin private/dihapus).")

    snip = items[0]["snippet"]
    thumb = snip.get("thumbnails", {})
    thumb_url = thumb.get("high", thumb.get("default", {})).get("url")

    return {
        "video_id": video_id,
        "title": snip["title"],
        "description": snip.get("description") or "(tidak ada deskripsi)",
        "channel": snip["channelTitle"],
        "link": f"https://www.youtube.com/watch?v={video_id}",
        "thumbnail": thumb_url,
        "published_at": snip["publishedAt"],
    }


def ambil_semua_konsep(session: Session) -> list[str]:
    def _tx(tx):
        result = tx.run("MATCH (k:Konsep) RETURN DISTINCT k.nama AS nama ORDER BY nama")
        return [r["nama"] for r in result]

    return session.execute_read(_tx)


_PROMPT_KLASIFIKASI = """Kamu adalah asisten klasifikasi video pembelajaran matematika.

Berikut informasi sebuah video YouTube{konteks_query}:
Judul: {judul}
Deskripsi: {deskripsi}

Berikut SELURUH daftar KONSEP yang ada di knowledge graph. Kamu HANYA boleh memilih dari daftar ini
-- SALIN PERSIS nama konsepnya sesuai penulisan di daftar (jangan diparafrase, jangan ditambah kata,
jangan digabung dengan kata lain), dan DILARANG membuat nama konsep baru di luar daftar:
{daftar_konsep}

Tugas: tentukan konsep MANAPUN dari daftar (boleh lebih dari satu topik/bab berbeda) yang BENAR-BENAR
dibahas secara substantif di video ini. Video sering membahas lebih dari satu konsep sekaligus
(mis. video "Persamaan Kuadrat" biasanya juga membahas "Faktorisasi Aljabar" sebagai teknik
penyelesaiannya) -- tangkap semua yang relevan.

Kalau tidak ada satupun konsep dari daftar yang benar-benar cocok, kembalikan list kosong.

Balas HANYA dengan JSON valid, tanpa teks lain, tanpa markdown code fence, format:
{{"konsep_terpilih": ["nama konsep -- SALIN PERSIS dari daftar di atas", "..."]}}
"""


def _clean_json_response(raw: str) -> str:
    return re.sub(r"^```(json)?|```$", "", raw.strip(), flags=re.MULTILINE).strip()


def klasifikasi_video_llm(
    client: genai.Client, model: str, judul: str, deskripsi: str,
    materi_query: Optional[str], daftar_konsep: list[str], log: LogFn, max_retry: int = 3,
) -> list[str]:
    if not daftar_konsep:
        return []

    konteks_query = (
        f' (dicari dengan query topik "{materi_query}" -- tapi video BISA SAJA membahas konsep '
        "dari topik lain juga, jangan batasi diri hanya ke topik pencarian ini)"
        if materi_query else ""
    )

    prompt = _PROMPT_KLASIFIKASI.format(
        konteks_query=konteks_query, judul=judul, deskripsi=deskripsi,
        daftar_konsep="\n".join(f"- {k}" for k in daftar_konsep),
    )

    for percobaan in range(max_retry):
        try:
            response = client.models.generate_content(model=model, contents=prompt)
            data = json.loads(_clean_json_response(response.text))
            hasil = data.get("konsep_terpilih", [])

            daftar_lower = {k.lower(): k for k in daftar_konsep}
            hasil_valid = [daftar_lower[h.lower()] for h in hasil if h.lower() in daftar_lower]
            ditolak = [h for h in hasil if h.lower() not in daftar_lower]
            if ditolak:
                log(f"    [ditolak, di luar closed vocabulary]: {ditolak}")

            return hasil_valid
        except json.JSONDecodeError:
            log(f"    gagal parse JSON, percobaan {percobaan + 1}/{max_retry}")
            time.sleep(2)
        except Exception as e:  # noqa: BLE001
            if "429" in str(e) or "rate" in str(e).lower():
                log("    kena rate limit, tunggu 20 detik...")
                time.sleep(20)
            else:
                log(f"    error: {e}")
                time.sleep(3)

    log(f"    GAGAL klasifikasi setelah {max_retry} percobaan -- ditandai list kosong.")
    return []


def _setup_constraint_materi(tx):
    tx.run("CREATE CONSTRAINT materi_id IF NOT EXISTS FOR (m:Materi) REQUIRE m.id IS UNIQUE")


def _simpan_materi_youtube(tx, video: dict, konsep_terklasifikasi: list[str]):
    """Simpan sebagai node `:Materi` generik (bukan `:MateriYoutube`) -- `tipe` jadi diskriminator
    sumber supaya pipeline materi lain (non-YouTube) bisa pakai label yang sama nanti."""
    tx.run(
        """
        MERGE (m:Materi {id: $id})
        SET m.judul = $judul, m.kontributor = $kontributor, m.sumber = $sumber, m.tipe = 'youtube',
            m.thumbnail = $thumbnail, m.published_at = $published_at,
            m.basis_klasifikasi = 'judul_deskripsi', m.status_validasi = 'valid'
        """,
        id=video["video_id"], judul=video["title"], kontributor=video["channel"],
        sumber=video["link"], thumbnail=video["thumbnail"], published_at=video["published_at"],
    )
    for nama_konsep in konsep_terklasifikasi:
        tx.run(
            """
            MATCH (m:Materi {id: $id})
            MATCH (k:Konsep {nama: $nama_konsep})
            MERGE (m)-[:MEMBAHAS_KONSEP]->(k)
            """,
            id=video["video_id"], nama_konsep=nama_konsep.lower(),
        )


def simpan_video_ke_kg(session: Session, video: dict, konsep_terklasifikasi: list[str]) -> None:
    session.execute_write(_setup_constraint_materi)
    session.execute_write(_simpan_materi_youtube, video, konsep_terklasifikasi)


# --- Edit & hapus video yang sudah tersimpan ---

def _ambil_video(tx, video_id: str) -> Optional[dict]:
    result = tx.run(
        """
        MATCH (m:Materi {id: $id, tipe: 'youtube'})
        OPTIONAL MATCH (m)-[:MEMBAHAS_KONSEP]->(k:Konsep)
        RETURN m.id AS video_id, m.judul AS judul, m.kontributor AS channel,
               m.sumber AS link, m.status_validasi AS status_validasi,
               collect(k.nama) AS konsep
        """,
        id=video_id,
    )
    record = result.single()
    return dict(record) if record and record["video_id"] is not None else None


def cari_video(session: Session, video_id: str) -> Optional[dict]:
    return session.execute_read(_ambil_video, video_id)


def update_video(session: Session, video_id: str, judul: Optional[str], konsep_baru: list[str]) -> Optional[dict]:
    """Edit judul (opsional) & timpa ulang daftar Konsep video yang sudah tersimpan. Konsep harus
    dari closed vocabulary yang sudah ada di KG -- nama yang gak ketemu diam-diam disaring, sama
    kayak alur konfirmasi klasifikasi. Return None kalau video_id gak ketemu."""

    if cari_video(session, video_id) is None:
        return None

    def _update(tx):
        if judul and judul.strip():
            tx.run("MATCH (m:Materi {id: $id}) SET m.judul = $judul", id=video_id, judul=judul.strip())
        tx.run("MATCH (:Materi {id: $id})-[r:MEMBAHAS_KONSEP]->(:Konsep) DELETE r", id=video_id)
        for nama_konsep in konsep_baru:
            tx.run(
                """
                MATCH (m:Materi {id: $id})
                MATCH (k:Konsep {nama: $nama_konsep})
                MERGE (m)-[:MEMBAHAS_KONSEP]->(k)
                """,
                id=video_id, nama_konsep=nama_konsep.strip().lower(),
            )

    session.execute_write(_update)
    return cari_video(session, video_id)


def hapus_video(session: Session, video_id: str) -> Optional[dict]:
    """Hapus node Materi video (dan relasi MEMBAHAS_KONSEP-nya lewat DETACH DELETE). Node `:Konsep`
    gak ikut dihapus. Return None kalau video_id gak ketemu."""

    ringkasan = cari_video(session, video_id)
    if ringkasan is None:
        return None

    def _hapus(tx):
        tx.run("MATCH (m:Materi {id: $id}) DETACH DELETE m", id=video_id)

    session.execute_write(_hapus)
    return ringkasan


# --- Orkestrasi end-to-end ---
#
# Sama kayak PDF (lihat komentar panjang di pdf_pipeline.py): dipecah preview -> confirm/discard
# supaya dosen bisa cek dulu konsep hasil klasifikasi LLM sebelum video beneran nempel ke KG.
# Bedanya sama PDF: video itu mode *klasifikasi* (closed vocabulary) -- dosen cuma boleh
# hapus/pilih dari Konsep yang SUDAH ADA di KG, gak boleh ngetik nama konsep baru bebas (kalau
# dipaksa, `_simpan_video` bakal diem-diem gak nyambungin apa-apa karena MATCH-nya gak ketemu).


def run_youtube_classification_preview(
    job_id: str, link: str, materi_query: Optional[str], settings: Settings, log: LogFn,
) -> dict:
    """Fetch metadata video + klasifikasi konsep lewat LLM, TANPA nulis apa pun ke Neo4j.
    Draft-nya disimpen di `youtube_draft_store`, nunggu dikonfirmasi lewat `confirm_youtube_classification`."""

    video_id = extract_video_id(link)
    log(f"video_id: {video_id}")

    video = fetch_video_snippet(video_id, settings.youtube_api_key)
    log(f"Judul: {video['title']}")

    with neo4j_session() as session:
        daftar_konsep = ambil_semua_konsep(session)
    log(f"Total konsep closed-vocabulary di KG: {len(daftar_konsep)}")

    if not daftar_konsep:
        raise ValueError(
            "Belum ada Konsep di Neo4j untuk dijadikan closed vocabulary. "
            "Jalankan ekstraksi PDF dulu (dan konfirmasi) sebelum klasifikasi video."
        )

    client = genai.Client(api_key=settings.gemini_api_key)
    konsep_terpilih = klasifikasi_video_llm(
        client, settings.gemini_model, judul=video["title"], deskripsi=video["description"],
        materi_query=materi_query, daftar_konsep=daftar_konsep, log=log,
    )
    log(f"Konsep terklasifikasi: {konsep_terpilih}")

    log("Klasifikasi selesai -- menunggu konfirmasi dosen sebelum disimpan ke Knowledge Graph.")

    preview = {
        "video_id": video["video_id"],
        "judul": video["title"],
        "channel": video["channel"],
        "link": video["link"],
        "thumbnail": video["thumbnail"],
        "konsep_terklasifikasi": konsep_terpilih,
        "relevan": len(konsep_terpilih) > 0,
        "status_penyimpanan": "menunggu_konfirmasi",
    }

    youtube_draft_store.save_draft(job_id, {"video": video, "daftar_konsep": daftar_konsep, "preview": preview})
    return preview


def confirm_youtube_classification(job_id: str, konsep_final: list[str]) -> Optional[dict]:
    """Simpan video + konsep (hasil editan dosen, HARUS subset dari closed vocabulary yang
    dikirim balik lewat draft) ke Neo4j. Konsep yang bukan bagian closed vocabulary otomatis
    disaring (dilewati diam-diam sama `_simpan_video`, jadi disaring duluan di sini biar
    responsenya jujur soal apa yang beneran kesimpan). Return None kalau draft gak ada."""

    from app.services.graph_confirmation import apply_once
    return youtube_draft_store.confirm(job_id, lambda draft: apply_once(job_id, lambda tx: _confirm_youtube(tx, draft, konsep_final)))


def _confirm_youtube(tx, draft, konsep_final):
    video, daftar_konsep = draft["video"], draft["daftar_konsep"]
    daftar_lower = {k.lower(): k for k in daftar_konsep}
    konsep_valid = [daftar_lower[k.strip().lower()] for k in konsep_final if k.strip().lower() in daftar_lower]

    _simpan_materi_youtube(tx, video, konsep_valid)

    return {
        "detail": "Video berhasil disimpan ke Knowledge Graph.",
        "video_id": video["video_id"],
        "judul": video["title"],
        "channel": video["channel"],
        "link": video["link"],
        "konsep_terklasifikasi": konsep_valid,
    }


def discard_youtube_draft(job_id: str) -> bool:
    """Buang draft klasifikasi tanpa nulis apa pun ke Neo4j. Return False kalau draft-nya udah gak ada."""
    return youtube_draft_store.discard(job_id)
