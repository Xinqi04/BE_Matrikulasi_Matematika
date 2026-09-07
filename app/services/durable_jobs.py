"""PostgreSQL storage. A single application process owns background execution."""
from psycopg.types.json import Jsonb
from app.postgres_client import postgres_connection

SCHEMA = """
CREATE TABLE IF NOT EXISTS background_jobs (
 id text PRIMARY KEY, type text NOT NULL, status text NOT NULL,
 log jsonb NOT NULL DEFAULT '[]', result jsonb, error text,
 created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS job_drafts (
 job_id text PRIMARY KEY REFERENCES background_jobs(id), kind text NOT NULL,
 data jsonb NOT NULL, state text NOT NULL DEFAULT 'pending', response jsonb,
 updated_at timestamptz NOT NULL DEFAULT now()
);
"""


def initialize():
    with postgres_connection() as conn:
        conn.execute(SCHEMA)


def save_draft(job_id, kind, data):
    with postgres_connection() as conn:
        conn.execute("INSERT INTO job_drafts(job_id,kind,data) VALUES (%s,%s,%s)", (job_id, kind, Jsonb(data)))
        conn.execute("UPDATE background_jobs SET status='done',result=%s,updated_at=now() WHERE id=%s", (Jsonb(data["preview"]), job_id))


def update_result(conn, job_id, state, response=None):
    patch = {"status_penyimpanan": state}
    if response is not None:
        patch["confirmation"] = response
    conn.execute("UPDATE background_jobs SET result=coalesce(result,'{}'::jsonb) || %s, updated_at=now() WHERE id=%s", (Jsonb(patch), job_id))


def confirm(job_id, kind, apply):
    # Lock held until both graph receipt and PostgreSQL completion are durable.
    with postgres_connection() as conn:
        row = conn.execute("SELECT * FROM job_drafts WHERE job_id=%s AND kind=%s FOR UPDATE", (job_id, kind)).fetchone()
        if row is None or row["state"] == "discarded":
            return None
        if row["state"] == "confirmed":
            return row["response"]
        response = apply(row["data"])
        conn.execute("UPDATE job_drafts SET state='confirmed',response=%s,updated_at=now() WHERE job_id=%s", (Jsonb(response), job_id))
        update_result(conn, job_id, "tersimpan", response)
        return response


def discard(job_id, kind):
    from app.services.graph_confirmation import read_receipt
    with postgres_connection() as conn:
        row = conn.execute("SELECT * FROM job_drafts WHERE job_id=%s AND kind=%s FOR UPDATE", (job_id, kind)).fetchone()
        if row is None or row["state"] == "confirmed":
            return False
        if row["state"] == "discarded":
            return True
        # A graph commit may have succeeded before PostgreSQL lost its connection.
        response = read_receipt(job_id)
        if response is not None:
            conn.execute("UPDATE job_drafts SET state='confirmed',response=%s,updated_at=now() WHERE job_id=%s", (Jsonb(response), job_id))
            update_result(conn, job_id, "tersimpan", response)
            return False
        conn.execute("UPDATE job_drafts SET state='discarded',updated_at=now() WHERE job_id=%s", (job_id,))
        update_result(conn, job_id, "dibuang")
        return True
