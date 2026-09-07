"""Opt in with RUN_PG_INTEGRATION=1; uses a disposable PostgreSQL schema."""
import os
import uuid
import unittest
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from unittest.mock import patch

import psycopg
from psycopg import sql
from psycopg.rows import dict_row
from app.config import get_settings
from app import job_manager
from app.services import durable_jobs


@unittest.skipUnless(os.getenv("RUN_PG_INTEGRATION") == "1", "requires local PostgreSQL")
class PostgresJobs(unittest.TestCase):
    def test_persistence_failure_and_concurrent_confirmation(self):
        settings = get_settings()
        schema = "test_jobs_" + uuid.uuid4().hex
        def connect():
            return psycopg.connect(host=settings.postgres_host, port=settings.postgres_port, dbname=settings.postgres_db,
                user=settings.postgres_user, password=settings.postgres_password, connect_timeout=5, row_factory=dict_row)

        @contextmanager
        def connection():
            with connect() as conn:
                conn.execute(sql.SQL("SET search_path TO {}").format(sql.Identifier(schema)))
                yield conn

        with connect() as conn:
            conn.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
        try:
            with patch.object(job_manager, "postgres_connection", connection), patch.object(durable_jobs, "postgres_connection", connection):
                durable_jobs.initialize()
                durable_jobs.initialize()  # existing schema upgrade is repeatable
                job = job_manager.create_job("pdf_extraction")
                job_manager.log(job.id, "hello")
                durable_jobs.save_draft(job.id, "pdf_extraction", {"preview": {"status_penyimpanan": "menunggu_konfirmasi"}})
                # Every operation opens a different connection: nothing relies on RAM.
                loaded = job_manager.get_job(job.id)
                self.assertEqual(loaded.status.value, "done")
                self.assertEqual(loaded.log, ["hello"])
                with self.assertRaises(RuntimeError):
                    durable_jobs.confirm(job.id, "pdf_extraction", lambda data: (_ for _ in ()).throw(RuntimeError("failed")))
                calls = []
                def apply(data):
                    calls.append(1)
                    return {"detail": "saved"}
                def confirm():
                    return durable_jobs.confirm(job.id, "pdf_extraction", apply)
                with ThreadPoolExecutor(max_workers=2) as pool:
                    results = list(pool.map(lambda _: confirm(), range(2)))
                self.assertEqual(results, [{"detail": "saved"}] * 2)
                self.assertEqual(len(calls), 1)
                self.assertEqual(job_manager.get_job(job.id).result["status_penyimpanan"], "tersimpan")
        finally:
            with connect() as conn:
                conn.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema)))
