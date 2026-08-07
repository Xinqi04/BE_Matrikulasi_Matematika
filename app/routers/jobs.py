from fastapi import APIRouter, HTTPException

from app.job_manager import get_job, list_jobs
from app.schemas import JobStatusResponse

router = APIRouter(prefix="/jobs", tags=["jobs"])


@router.get("", response_model=list[JobStatusResponse])
def get_all_jobs():
    return [JobStatusResponse(**j.model_dump()) for j in list_jobs()]


@router.get("/{job_id}", response_model=JobStatusResponse)
def get_job_status(job_id: str):
    job = get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job tidak ditemukan")
    return JobStatusResponse(**job.model_dump())
