"""Cache in-memory buat hasil ekstraksi PDF yang belum dikonfirmasi dosen.

Job (`job_manager`) nyimpen hasil ringkas (buat ditampilin di UI) di `JobRecord.result`,
tapi draft di sini nyimpen data LENGKAP (`unit_list` buat struktur Bab/SubBab + `unit_final`
buat konsep) yang dibutuhin `simpan_struktur_dan_konsep` pas dosen klik konfirmasi.
Sengaja gak disatuin sama job.result biar payload job API (yang di-serialize ke JSON tiap
polling) tetep ringkas.
"""

from __future__ import annotations

import threading
from typing import Optional

_drafts: dict[str, dict] = {}
_lock = threading.Lock()


def save_draft(job_id: str, data: dict) -> None:
    with _lock:
        _drafts[job_id] = data


def get_draft(job_id: str) -> Optional[dict]:
    with _lock:
        return _drafts.get(job_id)


def pop_draft(job_id: str) -> Optional[dict]:
    with _lock:
        return _drafts.pop(job_id, None)
