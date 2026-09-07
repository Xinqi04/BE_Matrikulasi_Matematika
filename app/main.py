from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.neo4j_client import close_driver
from app.config import get_settings
from app.upload_limits import UploadLimitMiddleware
from app.routers import admin, auth, dosen, jobs, kg, mahasiswa, pdf, youtube
from app.services import durable_jobs, graph_confirmation
from app.postgres_client import postgres_connection
from app.readiness import router as readiness_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    durable_jobs.initialize()
    graph_confirmation.initialize()
    # The executor still uses BackgroundTasks. Refuse a second process rather
    # than incorrectly interrupting that process's active jobs during startup.
    with postgres_connection() as owner:
        if not owner.execute("SELECT pg_try_advisory_lock(74201951) AS acquired").fetchone()["acquired"]:
            raise RuntimeError("Jalankan hanya satu proses backend untuk BackgroundTasks")
        owner.commit()
        with postgres_connection() as conn:
            conn.execute("UPDATE background_jobs SET status='error',error='Proses terputus saat backend berhenti. Silakan jalankan ulang.',updated_at=now() WHERE status IN ('pending','running')")
        try:
            yield
        finally:
            owner.execute("SELECT pg_advisory_unlock(74201951)")
            close_driver()


app = FastAPI(
    title="Matrikulasi Matematika KG API",
    description="Backend untuk ekstraksi konsep dari modul PDF dan klasifikasi materi YouTube ke Knowledge Graph.",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=get_settings().cors_origins,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(UploadLimitMiddleware)

app.include_router(auth.router)
app.include_router(admin.router)
app.include_router(dosen.router)
app.include_router(mahasiswa.router)
app.include_router(pdf.router)
app.include_router(youtube.router)
app.include_router(jobs.router)
app.include_router(kg.router)
app.include_router(readiness_router)


@app.get("/health", tags=["health"])
def health():
    return {"status": "ok"}
