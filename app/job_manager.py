import threading
import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Callable, Optional

from pydantic import BaseModel, Field


class JobStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    DONE = "done"
    ERROR = "error"


class JobRecord(BaseModel):
    id: str
    type: str
    status: JobStatus = JobStatus.PENDING
    log: list[str] = Field(default_factory=list)
    result: Optional[Any] = None
    error: Optional[str] = None
    created_at: datetime
    updated_at: datetime


_jobs: dict[str, JobRecord] = {}
_lock = threading.Lock()


def create_job(job_type: str) -> JobRecord:
    now = datetime.now(timezone.utc)
    job = JobRecord(id=str(uuid.uuid4()), type=job_type, created_at=now, updated_at=now)
    with _lock:
        _jobs[job.id] = job
    return job


def get_job(job_id: str) -> Optional[JobRecord]:
    with _lock:
        return _jobs.get(job_id)


def list_jobs() -> list[JobRecord]:
    with _lock:
        return sorted(_jobs.values(), key=lambda j: j.created_at, reverse=True)


def log(job_id: str, message: str) -> None:
    with _lock:
        job = _jobs.get(job_id)
        if job is None:
            return
        job.log.append(message)
        job.updated_at = datetime.now(timezone.utc)
    print(f"[job {job_id}] {message}")


def _set_status(job_id: str, status: JobStatus) -> None:
    with _lock:
        job = _jobs.get(job_id)
        if job is None:
            return
        job.status = status
        job.updated_at = datetime.now(timezone.utc)


def mark_done(job_id: str, result: Any) -> None:
    with _lock:
        job = _jobs.get(job_id)
        if job is None:
            return
        job.status = JobStatus.DONE
        job.result = result
        job.updated_at = datetime.now(timezone.utc)


def mark_error(job_id: str, error: str) -> None:
    with _lock:
        job = _jobs.get(job_id)
        if job is None:
            return
        job.status = JobStatus.ERROR
        job.error = error
        job.updated_at = datetime.now(timezone.utc)


def run_job(job_id: str, fn: Callable[[Callable[[str], None]], Any]) -> None:
    """Jalankan `fn` di background thread (dipanggil lewat FastAPI BackgroundTasks).

    `fn` menerima satu argumen: callback `log_fn(pesan)` buat lapor progress ke job log.
    """
    _set_status(job_id, JobStatus.RUNNING)
    try:
        result = fn(lambda msg: log(job_id, msg))
        mark_done(job_id, result)
    except Exception as exc:  # noqa: BLE001 - job runner wajib nangkep semua exception biar status ke-update, bukan bikin proses crash diam-diam
        mark_error(job_id, str(exc))
