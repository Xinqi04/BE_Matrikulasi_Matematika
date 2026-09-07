"""Persistent pdf drafts in PostgreSQL."""
from app.services import durable_jobs


def save_draft(job_id, data):
    durable_jobs.save_draft(job_id, "pdf_extraction", data)


def confirm(job_id, apply):
    return durable_jobs.confirm(job_id, "pdf_extraction", apply)


def discard(job_id):
    return durable_jobs.discard(job_id, "pdf_extraction")
