"""Cache in-memory buat hasil klasifikasi video YouTube yang belum dikonfirmasi dosen.
Pola sama persis kayak `pdf_draft_store` -- lihat komentar di sana."""

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
