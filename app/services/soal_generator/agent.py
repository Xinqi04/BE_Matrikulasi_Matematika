"""Agent generate draf soal per Bab pakai LLM (Gemini) -- dipanggil dari job background lewat
`job_manager.run_job`, pola sama seperti `pdf_pipeline.run_pdf_extraction_preview`. Hasilnya draf
MENTAH (belum ditulis ke Neo4j) -- dosen review/edit di frontend, baru disimpan lewat
`soal_pipeline.buat_soal()` pas endpoint confirm dipanggil.
"""

from __future__ import annotations

import json
import re
import time
from typing import Callable, Optional

from google import genai

from app.config import Settings
from app.neo4j_client import neo4j_session
from app.services import soal_pipeline
from app.services.soal_generator.prompts import build_prompt

LogFn = Callable[[str], None]

_TIPE_VALID = {"isian_singkat", "esai"}
_KESULITAN_VALID = {"mudah", "sedang", "sulit"}


def _clean_json_response(raw: str) -> str:
    return re.sub(r"^```(json)?|```$", "", raw.strip(), flags=re.MULTILINE).strip()


def _validasi_item(
    raw: dict, daftar_lower: dict[str, str], tipe_pin: Optional[str], kesulitan_pin: Optional[str],
) -> Optional[dict]:
    """Validasi + normalisasi satu item hasil LLM. Return None kalau item gak layak dipakai
    (teks kosong, tipe/kesulitan gak dikenal, atau semua konsep-nya di luar closed vocabulary)."""

    teks_soal = (raw.get("teks_soal") or "").strip()
    if not teks_soal:
        return None

    tipe = tipe_pin or raw.get("tipe")
    if tipe not in _TIPE_VALID:
        return None

    tingkat_kesulitan = kesulitan_pin or raw.get("tingkat_kesulitan")
    if tingkat_kesulitan not in _KESULITAN_VALID:
        return None

    konsep_mentah = raw.get("konsep")
    if not isinstance(konsep_mentah, list):
        return None
    konsep = [
        daftar_lower[k.strip().lower()] for k in konsep_mentah
        if isinstance(k, str) and k.strip().lower() in daftar_lower
    ]
    if not konsep:
        return None

    jawaban_referensi = (raw.get("jawaban_referensi") or "").strip() or None

    return {
        "teks_soal": teks_soal, "tipe": tipe, "tingkat_kesulitan": tingkat_kesulitan,
        "konsep": konsep, "jawaban_referensi": jawaban_referensi,
    }


def generate_soal_draft(
    bab_id: str, jumlah: int, tipe: Optional[str], tingkat_kesulitan: Optional[str],
    settings: Settings, log: LogFn, max_retry: int = 2,
) -> dict:
    with neo4j_session() as session:
        bab_info = soal_pipeline.get_bab_info(session, bab_id)
        konsep_detail = soal_pipeline.konsep_kandidat_detail(session, bab_id)

    if bab_info is None:
        raise ValueError(f"Bab '{bab_id}' tidak ditemukan.")
    if not konsep_detail:
        raise ValueError(
            "Bab ini belum punya konsep -- ekstrak/lengkapi konsep dulu sebelum generate soal."
        )

    log(f"Menyusun konteks Bab '{bab_info['nama']}' ({len(konsep_detail)} konsep tersedia)...")

    ringkasan = "\n".join([bab_info["summary"], *bab_info["subbab_summary"]]).strip()
    daftar_lower = {k["nama"].lower(): k["nama"] for k in konsep_detail}
    prompt = build_prompt(
        nomor=bab_info["nomor"], nama=bab_info["nama"], ringkasan=ringkasan,
        daftar_konsep=konsep_detail, jumlah=jumlah, tipe=tipe, tingkat_kesulitan=tingkat_kesulitan,
    )

    client = genai.Client(api_key=settings.gemini_api_key)
    items: list[dict] = []

    for percobaan in range(max_retry):
        log(f"Meminta LLM generate {jumlah} soal (percobaan {percobaan + 1}/{max_retry})...")
        try:
            response = client.models.generate_content(model=settings.gemini_model, contents=prompt)
            data = json.loads(_clean_json_response(response.text))
            if not isinstance(data, list):
                raise ValueError("Respons LLM bukan JSON array")

            for raw_item in data:
                if not isinstance(raw_item, dict):
                    continue
                valid = _validasi_item(raw_item, daftar_lower, tipe, tingkat_kesulitan)
                if valid:
                    items.append(valid)

            if items:
                break
        except (json.JSONDecodeError, ValueError):
            time.sleep(1)
        except Exception:  # noqa: BLE001 - job_manager nangkep & catat sebagai job error, bukan crash diam-diam
            time.sleep(1)

    if not items:
        raise ValueError("LLM gagal menghasilkan draf soal yang valid, coba generate ulang.")

    if len(items) < jumlah:
        log(f"Peringatan: cuma {len(items)} dari {jumlah} soal valid (sisanya gagal validasi konsep/format).")
    else:
        log(f"Berhasil generate {len(items)} draf soal.")

    return {"bab_id": bab_id, "items": items[:jumlah]}
