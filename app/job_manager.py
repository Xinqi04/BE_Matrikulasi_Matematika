from psycopg.types.json import Jsonb
from app.postgres_client import postgres_connection
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


def create_job(job_type: str) -> JobRecord:
    job_id = str(uuid.uuid4())
    with postgres_connection() as conn:
        row = conn.execute("INSERT INTO background_jobs(id,type,status) VALUES (%s,%s,'pending') RETURNING *", (job_id, job_type)).fetchone()
        return JobRecord(**row)


def get_job(job_id: str) -> Optional[JobRecord]:
    with postgres_connection() as conn:
        row = conn.execute("SELECT * FROM background_jobs WHERE id=%s", (job_id,)).fetchone()
        return JobRecord(**row) if row else None


def list_jobs() -> list[JobRecord]:
    with postgres_connection() as conn:
        return [JobRecord(**row) for row in conn.execute("SELECT * FROM background_jobs ORDER BY created_at DESC LIMIT 200").fetchall()]


def log(job_id: str, message: str) -> None:
    with postgres_connection() as conn:
        conn.execute("UPDATE background_jobs SET log=log || %s,updated_at=now() WHERE id=%s", (Jsonb([message]), job_id))


def _set_status(job_id: str, status: JobStatus) -> None:
    with postgres_connection() as conn:
        conn.execute("UPDATE background_jobs SET status=%s,updated_at=now() WHERE id=%s", (status.value, job_id))


def mark_done(job_id: str, result: Any) -> None:
    with postgres_connection() as conn:
        # Preserve confirmation/discard status if an early confirmation raced completion.
        conn.execute("UPDATE background_jobs SET status='done',result=%s || coalesce(result,'{}'::jsonb),error=NULL,updated_at=now() WHERE id=%s", (Jsonb(result), job_id))


def mark_error(job_id: str, error: str) -> None:
    with postgres_connection() as conn:
        conn.execute("UPDATE background_jobs SET status='error',error=%s,updated_at=now() WHERE id=%s", (error, job_id))


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
