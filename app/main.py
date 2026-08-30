from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.neo4j_client import close_driver
from app.routers import admin, auth, dosen, jobs, kg, mahasiswa, pdf, youtube


@asynccontextmanager
async def lifespan(app: FastAPI):
    yield
    close_driver()


app = FastAPI(
    title="Matrikulasi Matematika KG API",
    description="Backend untuk ekstraksi konsep dari modul PDF dan klasifikasi materi YouTube ke Knowledge Graph.",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(admin.router)
app.include_router(dosen.router)
app.include_router(mahasiswa.router)
app.include_router(pdf.router)
app.include_router(youtube.router)
app.include_router(jobs.router)
app.include_router(kg.router)


@app.get("/health", tags=["health"])
def health():
    return {"status": "ok"}
