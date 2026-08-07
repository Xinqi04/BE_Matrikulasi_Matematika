from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException

from app.auth import require_role
from app.config import Settings, get_settings
from app.job_manager import create_job, run_job
from app.neo4j_client import neo4j_session
from app.schemas import (
    HapusVideoOut,
    JobAccepted,
    VideoOut,
    VideoUpdateRequest,
    YoutubeClassifyRequest,
    YoutubeConfirmRequest,
    YoutubeConfirmResponse,
)
from app.services.youtube_pipeline import (
    confirm_youtube_classification,
    discard_youtube_draft,
    hapus_video,
    run_youtube_classification_preview,
    update_video,
)

router = APIRouter(prefix="/youtube", tags=["youtube"], dependencies=[Depends(require_role("dosen"))])


@router.post("/classify", response_model=JobAccepted, status_code=202)
def classify_youtube(
    body: YoutubeClassifyRequest,
    background_tasks: BackgroundTasks,
    settings: Settings = Depends(get_settings),
):
    """Mulai klasifikasi video di background. Job ini CUMA klasifikasi (ambil metadata + pilih
    konsep lewat LLM) -- belum nulis apa pun ke Knowledge Graph. Setelah job selesai (`status:
    done`), hasilnya ada di `job.result` buat direview dosen, lalu dikonfirmasi lewat
    `POST /youtube/confirm` (atau dibuang lewat `DELETE /youtube/draft/{job_id}`)."""

    job = create_job("youtube_classification")

    def _task():
        run_job(
            job.id,
            lambda log_fn: run_youtube_classification_preview(job.id, body.link, body.materi_query, settings, log_fn),
        )

    background_tasks.add_task(_task)

    return JobAccepted(job_id=job.id, status=job.status)


@router.post("/confirm", response_model=YoutubeConfirmResponse)
def confirm_classification(body: YoutubeConfirmRequest):
    """Simpan hasil klasifikasi (job `youtube_classification` yang statusnya `done`) ke Knowledge
    Graph, dengan daftar konsep sesuai editan dosen (harus dari closed vocabulary yang sama)."""

    result = confirm_youtube_classification(body.job_id, body.konsep)
    if result is None:
        raise HTTPException(status_code=404, detail="Draft klasifikasi tidak ditemukan (job_id salah atau sudah dikonfirmasi/dibuang)")
    return result


@router.delete("/draft/{job_id}")
def discard_classification(job_id: str):
    """Buang hasil klasifikasi tanpa menyimpannya ke Knowledge Graph."""

    if not discard_youtube_draft(job_id):
        raise HTTPException(status_code=404, detail="Draft klasifikasi tidak ditemukan")
    return {"detail": "Draft klasifikasi dibuang"}


@router.put("/video/{video_id}", response_model=VideoOut)
def update_video_endpoint(video_id: str, body: VideoUpdateRequest):
    """Edit judul & daftar konsep video yang sudah tersimpan di Knowledge Graph."""

    with neo4j_session() as session:
        result = update_video(session, video_id, body.judul, body.konsep)
    if result is None:
        raise HTTPException(status_code=404, detail="Video tidak ditemukan")
    return result


@router.delete("/video/{video_id}", response_model=HapusVideoOut)
def hapus_video_endpoint(video_id: str):
    """Hapus video materi dari Knowledge Graph. Ireversibel."""

    with neo4j_session() as session:
        ringkasan = hapus_video(session, video_id)
    if ringkasan is None:
        raise HTTPException(status_code=404, detail="Video tidak ditemukan")
    return HapusVideoOut(
        detail=f"Video '{ringkasan['judul']}' berhasil dihapus.",
        video_id=video_id,
        judul=ringkasan["judul"],
    )
