import re
import uuid
import pymupdf
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Depends, Form, HTTPException, UploadFile

from app.auth import require_role
from app.config import Settings, get_settings
from app.job_manager import create_job, run_job
from app.neo4j_client import neo4j_session
from app.schemas import HapusModulOut, JobAccepted, PdfConfirmRequest, PdfConfirmResponse
from app.services import kg_queries
from app.services.pdf_pipeline import confirm_pdf_extraction, discard_pdf_draft, hapus_modul, run_pdf_extraction_preview

router = APIRouter(prefix="/pdf", tags=["pdf"], dependencies=[Depends(require_role("dosen"))])


async def _save_pdf(file: UploadFile, settings: Settings) -> Path:
    limit = settings.max_pdf_upload_mb * 1024 * 1024
    upload_dir = Path(settings.upload_dir)
    upload_dir.mkdir(parents=True, exist_ok=True)
    dest_path = upload_dir / f"{uuid.uuid4().hex}.pdf"
    try:
        if file.size is not None and file.size > limit:
            raise HTTPException(413, f"Ukuran PDF maksimal {settings.max_pdf_upload_mb} MB")
        total = 0
        with dest_path.open("xb") as output:
            while chunk := await file.read(64 * 1024):
                total += len(chunk)
                if total > limit:
                    raise HTTPException(413, f"Ukuran PDF maksimal {settings.max_pdf_upload_mb} MB")
                output.write(chunk)
        try:
            # The file is bounded above. Parsing bytes avoids leaked native file
            # handles on malformed PDFs preventing cleanup on Windows.
            with pymupdf.open(stream=dest_path.read_bytes(), filetype="pdf") as document:
                if not document.is_pdf or document.needs_pass or document.page_count == 0:
                    raise ValueError("PDF kosong atau terenkripsi")
        except Exception as exc:
            raise HTTPException(400, "File harus berupa PDF valid, tidak kosong, dan tanpa password") from exc
        return dest_path
    except BaseException:
        dest_path.unlink(missing_ok=True)
        raise
    finally:
        await file.close()


def _slugify_modul_id(nama_domain: str) -> Optional[str]:
    slug = re.sub(r"[^a-z0-9]+", "_", nama_domain.strip().lower()).strip("_")
    return f"modul_{slug}" if slug else None


def _resolve_modul_id(modul_id: Optional[str], nama_domain: Optional[str], settings: Settings) -> str:
    """Modul ID kosong TIDAK BOLEH jatuh ke default hard-coded gitu aja -- itu yang bikin modul baru
    (mis. PDF PKN) numpuk/nimpa modul lain (mis. Matematika Dasar) yang kebetulan lagi jadi default,
    karena `MERGE (m:Modul {id: $id})` di pdf_pipeline nemu node yang sama persis. Modul ID kosong
    sekarang di-generate dari Nama Domain (unik per subjek), `default_modul_id` cuma dipakai kalau
    Modul ID **dan** Nama Domain dua-duanya kosong (skenario bootstrap modul pertama)."""
    if modul_id:
        return modul_id
    if nama_domain:
        auto = _slugify_modul_id(nama_domain)
        if auto:
            return auto
    return settings.default_modul_id


@router.post("/extract", response_model=JobAccepted, status_code=202)
async def extract_pdf(
    background_tasks: BackgroundTasks,
    file: UploadFile,
    modul_id: Optional[str] = Form(None),
    nama_domain: Optional[str] = Form(None),
    settings: Settings = Depends(get_settings),
):
    """Mulai ekstraksi PDF di background. Job ini CUMA mengekstrak (deteksi struktur + konsep
    lewat LLM) -- belum nulis apa pun ke Knowledge Graph. Setelah job selesai (`status: done`),
    hasilnya ada di `job.result` buat direview dosen, lalu dikonfirmasi lewat `POST /pdf/confirm`
    (atau dibuang lewat `DELETE /pdf/draft/{job_id}` kalau gak jadi dipakai)."""

    if not file.filename or not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="File harus berformat .pdf")

    resolved_modul_id = _resolve_modul_id(modul_id, nama_domain, settings)

    with neo4j_session() as session:
        modul_ada = next((m for m in kg_queries.list_modul(session) if m["id"] == resolved_modul_id), None)
    if modul_ada is not None and nama_domain and modul_ada["nama_domain"] != nama_domain.strip():
        raise HTTPException(
            status_code=409,
            detail=(
                f"Modul ID '{resolved_modul_id}' sudah dipakai untuk modul '{modul_ada['nama_domain']}'. "
                "Kalau memang mau menambah/memperbarui isi modul itu, samakan Nama Domain-nya. Kalau mau "
                "bikin modul baru, isi Modul ID secara eksplisit dengan ID yang belum dipakai."
            ),
        )

    dest_path = await _save_pdf(file, settings)

    job = create_job("pdf_extraction")

    def _task():
        run_job(
            job.id,
            lambda log_fn: run_pdf_extraction_preview(
                job.id, str(dest_path), resolved_modul_id, nama_domain, settings, log_fn,
            ),
        )

    background_tasks.add_task(_task)

    return JobAccepted(job_id=job.id, status=job.status)


@router.post("/confirm", response_model=PdfConfirmResponse)
def confirm_extraction(body: PdfConfirmRequest):
    """Simpan hasil ekstraksi (job `pdf_extraction` yang statusnya `done`) ke Knowledge Graph,
    dengan daftar konsep per unit sesuai editan dosen (boleh hapus/tambah dari hasil LLM)."""

    overrides = {
        item.unit_id: [{"nama": k.nama, "deskripsi": k.deskripsi} for k in item.konsep]
        for item in body.unit
    }
    result = confirm_pdf_extraction(body.job_id, overrides)
    if result is None:
        raise HTTPException(status_code=404, detail="Draft ekstraksi tidak ditemukan (job_id salah atau sudah dikonfirmasi/dibuang)")
    return result


@router.delete("/draft/{job_id}")
def discard_extraction(job_id: str):
    """Buang hasil ekstraksi tanpa menyimpannya ke Knowledge Graph."""

    if not discard_pdf_draft(job_id):
        raise HTTPException(status_code=404, detail="Draft ekstraksi tidak ditemukan")
    return {"detail": "Draft ekstraksi dibuang"}


@router.delete("/modul/{modul_id}", response_model=HapusModulOut)
def hapus_modul_endpoint(modul_id: str):
    """Hapus Modul beserta semua Bab/SubBab/Soal/jawaban di bawahnya. Konsep (vocabulary bersama)
    gak ikut dihapus. Ireversibel -- dosen harus konfirmasi dulu di frontend sebelum manggil ini."""

    with neo4j_session() as session:
        ringkasan = hapus_modul(session, modul_id)
    if ringkasan is None:
        raise HTTPException(status_code=404, detail="Modul tidak ditemukan")
    return HapusModulOut(
        detail=f"Modul '{ringkasan['nama_domain']}' dan seluruh isinya berhasil dihapus.",
        **ringkasan,
    )
