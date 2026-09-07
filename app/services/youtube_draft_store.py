"""Persistent youtube drafts in PostgreSQL."""
from app.services import durable_jobs


def save_draft(job_id, data):
    durable_jobs.save_draft(job_id, "youtube_classification", data)


def confirm(job_id, apply):
    return durable_jobs.confirm(job_id, "youtube_classification", apply)


def discard(job_id):
    return durable_jobs.discard(job_id, "youtube_classification")
