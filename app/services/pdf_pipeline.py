"""Ekstraksi konsep dari modul PDF ke Neo4j.

Port dari `pipeline_ekstraksi_konsep_kg.ipynb`. Alur: deteksi struktur (Daftar Isi) ->
susun unit ekstraksi (Bab/SubBab) -> semantic chunking unit yang kepanjangan -> ekstraksi
konsep per chunk (Gemini) -> konsolidasi antar sub-chunk (Gemini) -> simpan ke Neo4j.

Sesuai `vocabulary_policy.pdf_modul` di ontology_schema.json: jalur ini mode *ekstraksi*,
boleh membuat Konsep baru bebas dari teks.
"""

from __future__ import annotations

import json
import re
import time
from typing import Callable, Optional

import fitz
import numpy as np
from google import genai
from neo4j import Session

from app.config import Settings
from app.neo4j_client import neo4j_session
from app.services import pdf_draft_store

LogFn = Callable[[str], None]

_embedder = None


# --- Langkah 1: deteksi struktur dokumen ---

# Berapa banyak halaman awal yang dianggap "wajar" buat memuat halaman Daftar Isi. Kalau heading
# "DAFTAR ISI" gak ketemu dalam batas ini, dokumen dianggap memang gak punya Daftar Isi (bukan
# error -- Daftar Isi-nya cuma "kepotong" jauh di tengah dokumen).
BATAS_HALAMAN_CARI_DAFTAR_ISI = 10

_ROMAWI_NILAI = {"I": 1, "V": 5, "X": 10, "L": 50, "C": 100, "D": 500, "M": 1000}
_ROMAWI_URUT = ["I", "II", "III", "IV", "V", "VI", "VII", "VIII", "IX", "X",
                "XI", "XII", "XIII", "XIV", "XV", "XVI", "XVII", "XVIII", "XIX", "XX"]
_NOMOR_BAB_RE = r"\d+|[IVXLCDM]+"


def _romawi_ke_angka(token: str) -> Optional[int]:
    token = token.upper()
    if not token or any(c not in _ROMAWI_NILAI for c in token):
        return None
    total, sebelumnya = 0, 0
    for c in reversed(token):
        nilai = _ROMAWI_NILAI[c]
        if nilai < sebelumnya:
            total -= nilai
        else:
            total += nilai
            sebelumnya = nilai
    return total


def _angka_ke_romawi(n: int) -> Optional[str]:
    return _ROMAWI_URUT[n - 1] if 1 <= n <= len(_ROMAWI_URUT) else None


def _normalisasi_nomor_bab(token: str) -> Optional[str]:
    """Terima token nomor BAB dalam angka Arab atau Romawi, kembalikan angka Arab (string)."""
    token = token.strip()
    if token.isdigit():
        return str(int(token))
    angka = _romawi_ke_angka(token)
    return str(angka) if angka else None


def _normalisasi_nomor_sub(token: str) -> str:
    """Terima token nomor SubBAB dalam angka Arab atau huruf (A, B, C, ...), kembalikan angka Arab
    (string). Banyak modul melabeli SubBAB dengan huruf ("A. Judul", "B. Judul") alih-alih format
    "1.1" -- huruf itu perlu dikonversi supaya id SubBAB (`{bab}_sub{sub}`) tetap konsisten angka."""
    token = token.strip()
    if token.isdigit():
        return str(int(token))
    if len(token) == 1 and token.isalpha():
        return str(ord(token.upper()) - ord("A") + 1)
    return token


def _cek_kualitas_bookmark(toc: list) -> bool:
    """Bookmark dianggap layak dipakai kalau mulai dari BAB 1 dan levelnya rapi."""
    if not toc:
        return False
    bab_entries = [t for t in toc if re.match(r"^BAB\s+(" + _NOMOR_BAB_RE + r")", t[1].strip(), re.IGNORECASE)]
    if not bab_entries:
        return False
    token_pertama = re.match(r"^BAB\s+(" + _NOMOR_BAB_RE + r")", bab_entries[0][1].strip(), re.IGNORECASE).group(1)
    return _normalisasi_nomor_bab(token_pertama) == "1"


def _cari_halaman_daftar_isi(doc, batas_halaman: int = BATAS_HALAMAN_CARI_DAFTAR_ISI):
    """Cari heading 'DAFTAR ISI' di N halaman pertama saja. Return (full_text, toc_start) kalau
    ketemu, atau (full_text, None) kalau enggak -- full_text tetap dikembalikan biar gak baca ulang
    dokumen di pemanggil."""
    full_text = ""
    awal_text = None
    for i, page in enumerate(doc):
        full_text += page.get_text() + "\n"
        if i == batas_halaman - 1:
            awal_text = full_text

    if awal_text is None:  # dokumen lebih pendek dari batas_halaman
        awal_text = full_text

    m_toc = re.search(r"DAFTAR\s+ISI", awal_text, re.IGNORECASE)
    return full_text, (m_toc.end() if m_toc else None)


def _parse_daftar_isi(full_text: str, toc_start: int):
    """Parse halaman Daftar Isi jadi list BAB dan SubBAB. Toleran terhadap spasi
    tidak konsisten di sekitar titik (mis. '5. 1', '6 .1') dan nomor BAB Arab/Romawi."""
    toc_area = full_text[toc_start:toc_start + 8000]

    leader = r"[.…]{2,}"
    # Judul BAB di Daftar Isi ada 2 gaya: "BAB 1 – Judul .......... 12" (leader + nomor
    # halaman di baris yang sama) atau "BAB 1: Judul" polos tanpa leader/nomor halaman
    # (nomor halamannya nempel di SubBAB pertama, bukan di baris BAB itu sendiri) --
    # leader+halaman jadi opsional, dan separator boleh titik dua selain strip/en-dash.
    bab_re = re.compile(
        r"^\s*BAB\s+(" + _NOMOR_BAB_RE + r")\s*[:–\-]\s*([A-Z0-9 ]+?)\s*(?:" + leader + r"\s*\d+)?\s*$",
        re.MULTILINE,
    )
    sub_re = re.compile(r"^\s*(\d+)\s*\.\s*(\d+)\s+(.+?)\s*" + leader, re.MULTILINE)

    bab_matches = list(bab_re.finditer(toc_area))
    sub_matches = list(sub_re.finditer(toc_area))
    babs = []
    for m in bab_matches:
        nomor = _normalisasi_nomor_bab(m.group(1))
        if nomor is not None:
            babs.append({"nomor": nomor, "judul": m.group(2).strip()})
    subs = [{"bab": m.group(1), "sub": m.group(2), "judul": m.group(3).strip()} for m in sub_matches]

    if not babs:
        return None, None, None

    last_end = max([m.end() for m in bab_matches] + [m.end() for m in sub_matches])
    body_start_offset = toc_start + last_end
    return babs, subs, body_start_offset


def _cari_posisi_di_body(babs: list, subs: list, body_area: str) -> list[dict]:
    """Cocokkan tiap judul BAB/SubBAB ke posisi karakter di body teks. Nomor BAB dicari dalam
    bentuk Arab MAUPUN Romawi karena body kadang beda gaya penomoran dari Daftar Isi."""
    unit_list = []
    for b in babs:
        varian_nomor = {b["nomor"]}
        romawi = _angka_ke_romawi(int(b["nomor"]))
        if romawi:
            varian_nomor.add(romawi)
        alternasi = "|".join(re.escape(v) for v in varian_nomor)
        # Gak wajib ada separator/judul di baris yang sama -- banyak dokumen naro judul BAB di
        # baris berikutnya (mis. "BAB  1" lalu "SEJARAH" di baris baru).
        p = re.compile(r"^\s*BAB\s+(?:" + alternasi + r")\b", re.MULTILINE)
        mm = p.search(body_area)
        if mm:
            unit_list.append({"level": "bab", "bab": b["nomor"], "sub": None,
                               "judul": b["judul"], "pos": mm.start()})

    for s in subs:
        p = re.compile(r"^\s*" + re.escape(s["bab"]) + r"\s*\.\s*" + re.escape(s["sub"]) + r"\s+[A-Za-z]",
                        re.MULTILINE)
        mm = p.search(body_area)
        if mm:
            unit_list.append({"level": "subbab", "bab": s["bab"], "sub": s["sub"],
                               "judul": s["judul"], "pos": mm.start()})

    unit_list.sort(key=lambda x: x["pos"])
    return unit_list


def _toc_ke_unit_list(doc, toc: list) -> list[dict]:
    """Konversi bookmark PDF (`doc.get_toc()`) langsung jadi unit_list, tanpa lewat parsing Daftar
    Isi. Level 1 -> BAB, level 2 -> SubBAB (level lebih dalam dari itu diabaikan). Posisi tiap
    entry dicari dengan mencocokkan judulnya ke teks halaman tujuan bookmark tsb."""
    page_offsets = [0]
    full_text = ""
    for page in doc:
        full_text += page.get_text() + "\n"
        page_offsets.append(len(full_text))

    nomor_bab_urut = 0
    sub_urut_per_bab: dict[str, int] = {}
    unit_list = []

    for level, judul, nomor_halaman in toc:
        if level > 2:
            continue
        judul = judul.strip()
        if not judul:
            continue

        idx_halaman = max(0, min(nomor_halaman - 1, len(page_offsets) - 2))
        area_awal, area_akhir = page_offsets[idx_halaman], page_offsets[idx_halaman + 1]
        posisi = area_awal
        cari = re.search(re.escape(judul[:30]), full_text[area_awal:area_akhir])
        if cari:
            posisi = area_awal + cari.start()

        if level == 1:
            nomor_bab_urut += 1
            nomor_bab = str(nomor_bab_urut)
            sub_urut_per_bab[nomor_bab] = 0
            unit_list.append({"level": "bab", "bab": nomor_bab, "sub": None, "judul": judul, "pos": posisi})
        else:
            if nomor_bab_urut == 0:
                continue  # SubBAB tanpa BAB induk (bookmark cacat) -- lewati
            nomor_bab = str(nomor_bab_urut)
            sub_urut_per_bab[nomor_bab] += 1
            unit_list.append({"level": "subbab", "bab": nomor_bab, "sub": str(sub_urut_per_bab[nomor_bab]),
                               "judul": judul, "pos": posisi})

    unit_list.sort(key=lambda x: x["pos"])
    for i, u in enumerate(unit_list):
        u["mulai"] = u["pos"]
        u["selesai"] = unit_list[i + 1]["pos"] if i + 1 < len(unit_list) else len(full_text)
        u["teks"] = full_text[u["mulai"]:u["selesai"]].strip()

    return unit_list


# --- Langkah 1b: fallback LLM kalau Daftar Isi gak ada/gak terparse ---

_PROMPT_PARSE_DAFTAR_ISI = """Berikut teks halaman "Daftar Isi" yang diekstrak dari sebuah modul/buku ajar.
Formatnya bisa berantakan (spasi tidak konsisten, penomoran BAB angka Arab/Romawi, penomoran SubBAB
angka atau huruf (A, B, C, ...), dengan/tanpa nomor halaman).

Ekstrak daftar BAB dan SubBAB dari teks ini. Abaikan entri non-materi seperti "Kata Pengantar",
"Daftar Isi", "Daftar Pustaka", "Lampiran".

Balas HANYA dengan JSON valid, tanpa teks lain, tanpa markdown code fence, format:
{{
  "bab": [{{"nomor": "1", "judul": "PENDAHULUAN"}}],
  "subbab": [{{"bab": "1", "sub": "1", "judul": "Latar Belakang"}}]
}}

Nomor BAB HARUS angka Arab (konversi dari Romawi kalau perlu). Nomor SubBAB HARUS angka Arab urut per
BAB (kalau aslinya berlabel huruf A/B/C/D, konversi A->1, B->2, C->3, dst -- JANGAN kirim huruf
mentah). Kalau tidak ada SubBAB sama sekali, "subbab" boleh list kosong.

Teks Daftar Isi:
\"\"\"
{teks}
\"\"\"
"""

_PROMPT_DETEKSI_STRUKTUR_BODY = """Berikut teks isi (body) sebuah modul/buku ajar yang TIDAK punya halaman
Daftar Isi yang bisa dipakai. Identifikasi heading BAB dan SubBAB langsung dari teks ini (heading biasanya
berupa baris pendek, sering huruf kapital semua, diawali "BAB <nomor>" atau nomor bertingkat spt "1.1").

Balas HANYA dengan JSON valid, tanpa teks lain, tanpa markdown code fence, format:
{{
  "unit": [
    {{"level": "bab", "bab": "1", "sub": null, "judul": "PENDAHULUAN", "heading_persis": "BAB 1 PENDAHULUAN"}},
    {{"level": "subbab", "bab": "1", "sub": "1", "judul": "Latar Belakang", "heading_persis": "1.1 Latar Belakang"}}
  ]
}}

"heading_persis" HARUS berupa substring yang PERSIS SAMA (huruf besar/kecil & spasi apa adanya) dengan
yang ada di teks di bawah, supaya posisinya bisa dicari lewat pencarian string biasa. Urutkan sesuai
urutan kemunculan di teks. Nomor BAB HARUS angka Arab. Nomor SubBAB HARUS angka Arab urut per BAB
(kalau aslinya berlabel huruf A/B/C/D, konversi A->1, B->2, C->3, dst -- JANGAN kirim huruf mentah).

Teks:
\"\"\"
{teks}
\"\"\"
"""


def _panggil_llm_json(client: genai.Client, model: str, prompt: str, log: LogFn, label: str,
                       max_retry: int = 3) -> Optional[dict]:
    for percobaan in range(max_retry):
        try:
            response = client.models.generate_content(model=model, contents=prompt)
            return json.loads(_clean_json_response(response.text))
        except json.JSONDecodeError:
            log(f"  [{label}] gagal parse JSON, percobaan {percobaan + 1}/{max_retry}")
            time.sleep(2)
        except Exception as e:  # noqa: BLE001
            if "429" in str(e) or "rate" in str(e).lower():
                log(f"  [{label}] kena rate limit, tunggu 20 detik...")
                time.sleep(20)
            else:
                log(f"  [{label}] error: {e}")
                time.sleep(3)
    log(f"  [{label}] GAGAL setelah {max_retry} percobaan.")
    return None


_BARIS_BERLEADER_RE = re.compile(r"^.{1,120}?[.…]{2,}\s*\d+\s*$", re.MULTILINE)


def _perkirakan_akhir_daftar_isi(toc_area: str) -> int:
    """Cari akhir wilayah Daftar Isi yang sebenarnya (bukan tebakan panjang tetap): ambil posisi
    akhir baris "leader titik/elipsis + nomor halaman" TERAKHIR di dalam `toc_area` -- pola ini
    ada di hampir semua gaya Daftar Isi (Arab, Romawi, atau berlabel huruf) selama tiap entrinya
    diakhiri nomor halaman. Kalau gak ada baris begitu sama sekali, anggap seluruh `toc_area`
    masih bagian dari Daftar Isi (gak motong apa pun)."""
    matches = list(_BARIS_BERLEADER_RE.finditer(toc_area))
    return matches[-1].end() if matches else len(toc_area)


def _daftar_isi_via_llm(client: genai.Client, model: str, toc_area: str, log: LogFn):
    data = _panggil_llm_json(client, model, _PROMPT_PARSE_DAFTAR_ISI.format(teks=toc_area),
                              log, label="parse-daftar-isi")
    if not data or not data.get("bab"):
        return None, None

    babs = [{"nomor": _normalisasi_nomor_bab(str(b["nomor"])) or str(b["nomor"]).strip(),
             "judul": str(b["judul"]).strip()} for b in data.get("bab", [])]
    subs = [{"bab": str(s["bab"]).strip(), "sub": _normalisasi_nomor_sub(str(s["sub"])),
             "judul": str(s["judul"]).strip()} for s in data.get("subbab", [])]
    return babs, subs


def _struktur_body_via_llm(client: genai.Client, model: str, full_text: str, log: LogFn,
                            batas_karakter: int = 40000) -> Optional[list[dict]]:
    """Last resort: gak ada Daftar Isi sama sekali, minta LLM cari heading BAB/SubBAB langsung
    dari body. Dibatasi `batas_karakter` biar biaya/latensi gak meledak untuk dokumen panjang."""
    teks = full_text[:batas_karakter]
    data = _panggil_llm_json(client, model, _PROMPT_DETEKSI_STRUKTUR_BODY.format(teks=teks),
                              log, label="deteksi-struktur-body")
    if not data or not data.get("unit"):
        return None

    unit_list, posisi_terakhir = [], -1
    for u in data["unit"]:
        heading = str(u.get("heading_persis", ""))
        if not heading:
            continue
        pos = teks.find(heading)
        if pos == -1 or pos <= posisi_terakhir:
            continue  # gak ketemu persis, atau LLM ngasih urutan mundur/halusinasi -- lewati
        posisi_terakhir = pos
        level = u.get("level")
        if level not in ("bab", "subbab"):
            continue
        unit_list.append({
            "level": level, "bab": str(u.get("bab", "")).strip(),
            "sub": _normalisasi_nomor_sub(str(u["sub"])) if level == "subbab" and u.get("sub") is not None else None,
            "judul": str(u.get("judul", "")).strip(), "pos": pos,
        })

    if not unit_list:
        return None

    unit_list.sort(key=lambda x: x["pos"])
    for i, u in enumerate(unit_list):
        u["mulai"] = u["pos"]
        u["selesai"] = unit_list[i + 1]["pos"] if i + 1 < len(unit_list) else len(teks)
        u["teks"] = teks[u["mulai"]:u["selesai"]].strip()
    return unit_list


def detect_struktur(pdf_path: str, log: LogFn, client: Optional[genai.Client] = None,
                     model: Optional[str] = None) -> list[dict]:
    doc = fitz.open(pdf_path)

    toc = doc.get_toc()
    if _cek_kualitas_bookmark(toc):
        log(f"Bookmark PDF ada {len(toc)} entri, kualitas layak -> dipakai langsung.")
        unit_list = _toc_ke_unit_list(doc, toc)
        log(f"Struktur terdeteksi dari bookmark PDF: {len(unit_list)} unit total.")
        return unit_list

    log(f"Bookmark PDF ada {len(toc)} entri, kualitas tidak layak -> coba Daftar Isi.")

    full_text, toc_start = _cari_halaman_daftar_isi(doc)
    babs = subs = body_start_offset = None
    if toc_start is not None:
        babs, subs, body_start_offset = _parse_daftar_isi(full_text, toc_start)

    if babs is None and toc_start is not None and client is not None:
        log("Daftar Isi ketemu tapi gak terparse regex -> coba parse lewat LLM.")
        toc_area = full_text[toc_start:toc_start + 8000]
        babs, subs = _daftar_isi_via_llm(client, model, toc_area, log)
        body_start_offset = toc_start + _perkirakan_akhir_daftar_isi(toc_area) if babs else None

    if babs is not None:
        body_area = full_text[body_start_offset:]
        unit_list = _cari_posisi_di_body(babs, subs, body_area)
        if unit_list:
            for i, u in enumerate(unit_list):
                u["mulai"] = u["pos"]
                u["selesai"] = unit_list[i + 1]["pos"] if i + 1 < len(unit_list) else len(body_area)
                u["teks"] = body_area[u["mulai"]:u["selesai"]].strip()
            log(f"Struktur terdeteksi dari Daftar Isi: {len(babs)} BAB, {len(subs)} SubBAB, "
                f"{len(unit_list)} unit total.")
            return unit_list
        log(f"Daftar Isi terparse ({len(babs)} BAB) tapi 0 unit cocok ke body -- format heading "
            "body kemungkinan beda gaya dari Daftar Isi.")

    if toc_start is None:
        log(f"'DAFTAR ISI' gak ditemukan di {BATAS_HALAMAN_CARI_DAFTAR_ISI} halaman pertama -> "
            "dianggap dokumen gak punya Daftar Isi.")
    elif babs is None:
        log("Parsing Daftar Isi gagal total (regex maupun LLM).")

    if client is None:
        raise NotImplementedError(
            "Daftar Isi tidak ditemukan/tidak terparse di PDF ini, dan fallback LLM tidak tersedia "
            "(client Gemini gak dikasih ke detect_struktur)."
        )

    log("Coba deteksi struktur langsung dari body pakai LLM (last resort)...")
    unit_list = _struktur_body_via_llm(client, model, full_text, log)
    if not unit_list:
        raise NotImplementedError(
            "Struktur dokumen gak berhasil dideteksi lewat bookmark, Daftar Isi, maupun LLM. "
            "Perlu deteksi struktur manual untuk PDF ini."
        )

    log(f"Struktur terdeteksi lewat LLM (body scan): {len(unit_list)} unit total.")
    return unit_list


# --- Langkah 2-3: susun unit ekstraksi final ---

def _bersihkan_teks(teks: str) -> str:
    return re.sub(r"\s+", " ", teks).strip()


def susun_unit_ekstraksi(unit_list: list[dict]) -> list[dict]:
    """- BAB dengan SubBAB -> unit ekstraksi = tiap SubBAB
    - BAB tanpa SubBAB   -> unit ekstraksi = BAB itu sendiri
    """
    bab_numbers_dengan_sub = {u["bab"] for u in unit_list if u["level"] == "subbab"}

    unit_final = []
    for u in unit_list:
        if u["level"] == "bab" and u["bab"] in bab_numbers_dengan_sub:
            continue
        u["teks"] = _bersihkan_teks(u["teks"])
        unit_final.append(u)

    return unit_final


# --- Langkah 4: semantic chunking ---

def _get_embedder():
    global _embedder
    if _embedder is None:
        from sentence_transformers import SentenceTransformer
        _embedder = SentenceTransformer("paraphrase-multilingual-MiniLM-L12-v2")
    return _embedder


def _split_kalimat(teks: str) -> list[str]:
    kalimat = re.split(r"(?<=[.!?])\s+", teks.strip())
    return [k for k in kalimat if k.strip()]


def semantic_chunk(teks: str, max_chars: int, similarity_drop_threshold: float = 0.25) -> list[str]:
    if len(teks) <= max_chars:
        return [teks]

    kalimat = _split_kalimat(teks)
    if len(kalimat) <= 1:
        return [teks[i:i + max_chars] for i in range(0, len(teks), max_chars)]

    embedder = _get_embedder()
    embeddings = embedder.encode(kalimat, normalize_embeddings=True)

    sims = [float(np.dot(embeddings[i], embeddings[i + 1])) for i in range(len(embeddings) - 1)]

    chunks, current, current_len = [], [], 0
    for i, k in enumerate(kalimat):
        current.append(k)
        current_len += len(k)

        akhir_karena_panjang = current_len >= max_chars
        akhir_karena_topik_beda = (
            i < len(sims) and sims[i] < similarity_drop_threshold and current_len > max_chars * 0.4
        )

        if akhir_karena_panjang or akhir_karena_topik_beda:
            chunks.append(" ".join(current))
            current, current_len = [], 0

    if current:
        chunks.append(" ".join(current))

    return chunks


# --- Langkah 5: ekstraksi konsep dengan LLM ---

_PROMPT_EKSTRAKSI = """Kamu adalah asisten ekstraksi konsep matematika dari materi ajar.

Baca teks di bawah ini (bagian dari "{judul_unit}", modul {nama_domain}), lalu ekstrak HANYA konsep-konsep
UTAMA yang dijelaskan di dalamnya -- bukan seluruh istilah atau langkah kecil yang cuma disebut sekilas.

Ambil konsep dari dua sinyal:
1. Definisi eksplisit -- kalimat berpola "X disebut Y", "Y didefinisikan sebagai X", atau heading "Definisi ...".
2. Prosedur/rumus utama yang dijelaskan tanpa kalimat definisi eksplisit.

Aturan penting supaya hasil tidak kebanyakan konsep receh:
- Gabungkan variasi dari SATU aturan/prosedur yang sama jadi SATU konsep induk. Contoh: penjumlahan,
  pengurangan, perkalian, pembagian bilangan rasional itu semua variasi dari "Operasi Bilangan Rasional" --
  JANGAN dipecah jadi 4 konsep terpisah, kecuali salah satunya punya keunikan konseptual sendiri.
- Skip istilah yang cuma disebut sekilas tanpa penjelasan berarti (notasi simbol semata, definisi satu
  baris tanpa elaborasi lebih lanjut).
- Satu konsep = satu ide matematika yang berdiri sendiri dan cukup penting untuk diuji terpisah di soal
  ujian (contoh: "Diskriminan" layak jadi konsep, "cara menulis akar kuadrat pakai simbol V" tidak layak).
- Ekstrak MAKSIMAL {maks_konsep} konsep paling penting dari teks ini. Kalau teksnya memang cuma punya
  sedikit ide inti, boleh kurang dari itu -- jangan dipaksa penuhi kuota.

Balas HANYA dengan JSON valid, tanpa teks lain, tanpa markdown code fence, format:
{{
  "konsep": ["nama konsep 1", "nama konsep 2"]
}}

Teks:
\"\"\"
{teks}
\"\"\"
"""

_PROMPT_KONSOLIDASI = """Berikut daftar kandidat konsep matematika yang diekstrak dari beberapa potongan teks
BAB/SubBAB yang sama: "{judul_unit}". Karena diekstrak per potongan secara terpisah, ada kemungkinan nama
yang sama/mirip muncul berkali-kali dengan penulisan sedikit berbeda (mis. "Evaluasi Fungsi" dan
"Evaluasi Nilai Fungsi" itu konsep yang sama).

Gabungkan konsep yang maknanya sama jadi satu nama saja (pilih penulisan yang paling jelas/baku).
Konsep yang benar-benar berbeda maknanya tetap dipisah.

Daftar kandidat:
{daftar}

Balas HANYA dengan JSON valid, tanpa teks lain, format:
{{"konsep_final": ["nama 1", "nama 2"]}}
"""


def _clean_json_response(raw: str) -> str:
    return re.sub(r"^```(json)?|```$", "", raw.strip(), flags=re.MULTILINE).strip()


def ekstrak_konsep_llm(
    client: genai.Client, model: str, teks: str, judul_unit: str, nama_domain: str,
    maks_konsep: int, log: LogFn, max_retry: int = 3,
) -> list[str]:
    prompt = _PROMPT_EKSTRAKSI.format(
        judul_unit=judul_unit, nama_domain=nama_domain, teks=teks, maks_konsep=maks_konsep,
    )

    for percobaan in range(max_retry):
        try:
            response = client.models.generate_content(model=model, contents=prompt)
            data = json.loads(_clean_json_response(response.text))
            return data.get("konsep", [])
        except json.JSONDecodeError:
            log(f"  [{judul_unit}] gagal parse JSON, percobaan {percobaan + 1}/{max_retry}")
            time.sleep(2)
        except Exception as e:  # noqa: BLE001
            if "429" in str(e) or "rate" in str(e).lower():
                log(f"  [{judul_unit}] kena rate limit, tunggu 20 detik...")
                time.sleep(20)
            else:
                log(f"  [{judul_unit}] error: {e}")
                time.sleep(3)

    log(f"  [{judul_unit}] GAGAL setelah {max_retry} percobaan -- lewati.")
    return []


def konsolidasi_konsep_llm(
    client: genai.Client, model: str, daftar_kandidat: list[str], judul_unit: str,
    log: LogFn, max_retry: int = 3,
) -> list[str]:
    if not daftar_kandidat:
        return []

    daftar_unik_kasar = sorted(set(daftar_kandidat))
    if len(daftar_unik_kasar) <= 1:
        return daftar_unik_kasar

    prompt = _PROMPT_KONSOLIDASI.format(
        judul_unit=judul_unit, daftar="\n".join(f"- {k}" for k in daftar_unik_kasar),
    )

    for percobaan in range(max_retry):
        try:
            response = client.models.generate_content(model=model, contents=prompt)
            data = json.loads(_clean_json_response(response.text))
            return data.get("konsep_final", daftar_unik_kasar)
        except json.JSONDecodeError:
            log(f"  [konsolidasi:{judul_unit}] gagal parse JSON, percobaan {percobaan + 1}/{max_retry}")
            time.sleep(2)
        except Exception as e:  # noqa: BLE001
            if "429" in str(e) or "rate" in str(e).lower():
                log(f"  [konsolidasi:{judul_unit}] rate limit, tunggu 20 detik...")
                time.sleep(20)
            else:
                log(f"  [konsolidasi:{judul_unit}] error: {e}")
                time.sleep(3)

    log(f"  [konsolidasi:{judul_unit}] GAGAL -- pakai daftar unik kasar apa adanya.")
    return daftar_unik_kasar


# --- Langkah 6: simpan ke Neo4j ---

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


def _simpan_konsep(tx, unit_id: str, konsep_list: list[str]):
    for nama_konsep in konsep_list:
        nama_bersih = nama_konsep.strip().lower()
        tx.run(
            """
            MERGE (k:Konsep {nama: $nama})
            WITH k
            MATCH (u {id: $unit_id})
            MERGE (u)-[:HAS_KONSEP]->(k)
            """,
            nama=nama_bersih, unit_id=unit_id,
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
        label = f"BAB {u['bab']}" if u["level"] == "bab" else f"{u['bab']}.{u['sub']}"
        log(f"Konsep ditempel: {label} - {len(konsep_list)} konsep")

    return total_konsep


# --- Orkestrasi end-to-end ---
#
# Alur dipecah jadi dua tahap biar dosen bisa REVIEW hasil ekstraksi LLM (hapus konsep yang
# gak sesuai, tambah konsep manual) SEBELUM apa pun ditulis ke Neo4j:
#
#   1. `run_pdf_extraction_preview` -- dipanggil dari job background. Deteksi struktur + ekstrak
#      konsep lewat LLM, TAPI belum nyentuh Neo4j sama sekali. Hasil lengkap (`unit_list` +
#      `unit_final`) disimpen di `pdf_draft_store` (keyed by job_id), sementara ringkasannya
#      (buat ditampilin di UI) jadi `job.result`.
#   2. `confirm_pdf_extraction` -- dipanggil pas dosen klik "Simpan". Ambil draft dari cache,
#      timpa `hasil_konsep` tiap unit sesuai editan dosen, baru panggil `simpan_struktur_dan_konsep`.
#
# Kalau dosen gak jadi simpan, `discard_pdf_draft` cukup buang draft dari cache -- gak ada
# jejak apa pun di Neo4j.


def _label_unit(u: dict) -> str:
    return f"BAB {u['bab']}" if u["level"] == "bab" else f"{u['bab']}.{u['sub']}"


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
    """Ekstraksi struktur + konsep dari PDF TANPA nulis apa pun ke Neo4j. Hasil lengkap
    disimpen di `pdf_draft_store` supaya bisa dikonfirmasi/dikoreksi lewat `confirm_pdf_extraction`."""

    nama_domain = nama_domain or settings.default_nama_domain
    client = genai.Client(api_key=settings.gemini_api_key)

    log(f"Mendeteksi struktur dokumen: {pdf_path}")
    unit_list = detect_struktur(pdf_path, log, client=client, model=settings.gemini_model)

    unit_final = susun_unit_ekstraksi(unit_list)
    log(f"Total unit final untuk diekstraksi: {len(unit_final)}")

    for u in unit_final:
        u["sub_chunks"] = semantic_chunk(u["teks"], max_chars=settings.max_chars_per_chunk)
    total_sub_chunks = sum(len(u["sub_chunks"]) for u in unit_final)
    log(f"Total sub-chunk siap diekstraksi LLM: {total_sub_chunks}")

    for u in unit_final:
        label = _label_unit(u)
        log(f"Ekstraksi {label} - {u['judul']} ({len(u['sub_chunks'])} sub-chunk)...")

        semua_konsep: list[str] = []
        for sc in u["sub_chunks"]:
            konsep_chunk = ekstrak_konsep_llm(
                client, settings.gemini_model, sc, judul_unit=f"{label} - {u['judul']}",
                nama_domain=nama_domain, maks_konsep=settings.maks_konsep_per_chunk, log=log,
            )
            semua_konsep.extend(konsep_chunk)
            time.sleep(4)  # jaga rate limit free tier

        if len(u["sub_chunks"]) > 1 and semua_konsep:
            sebelum = len(semua_konsep)
            semua_konsep = konsolidasi_konsep_llm(
                client, settings.gemini_model, semua_konsep, judul_unit=f"{label} - {u['judul']}", log=log,
            )
            log(f"  konsolidasi: {sebelum} -> {len(semua_konsep)} konsep")
            time.sleep(4)

        u["hasil_konsep"] = semua_konsep
        log(f"  -> {len(semua_konsep)} konsep final")

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


def confirm_pdf_extraction(job_id: str, konsep_overrides: dict[str, list[str]]) -> Optional[dict]:
    """Timpa `hasil_konsep` tiap unit sesuai editan dosen (`konsep_overrides`: unit_id -> daftar
    konsep final), lalu tulis struktur + konsep ke Neo4j. Return None kalau draft-nya gak ada
    (job_id salah, atau sudah dikonfirmasi/dibuang sebelumnya)."""

    draft = pdf_draft_store.pop_draft(job_id)
    if draft is None:
        return None

    modul_id, nama_domain = draft["modul_id"], draft["nama_domain"]
    unit_list, unit_final = draft["unit_list"], draft["unit_final"]

    for u in unit_final:
        unit_id = _hitung_unit_id(modul_id, u)
        if unit_id in konsep_overrides:
            u["hasil_konsep"] = [k.strip() for k in konsep_overrides[unit_id] if k.strip()]

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
