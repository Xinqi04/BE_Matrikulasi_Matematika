import asyncio
import io
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pymupdf
from fastapi import FastAPI, HTTPException, UploadFile
from fastapi.testclient import TestClient

from app.auth import get_current_user
from app.routers import jobs
from app.routers.pdf import _save_pdf
from app.services.ujian_modul_repo import InvalidSubmission, submit_ujian
from app.upload_limits import UploadLimitMiddleware


class ProductionGuards(unittest.TestCase):
    def test_jobs_require_dosen(self):
        app = FastAPI()
        app.include_router(jobs.router)
        client = TestClient(app)
        for path in ("/jobs", "/jobs/missing"):
            self.assertEqual(client.get(path).status_code, 401)
        for role in ("mahasiswa", "admin"):
            app.dependency_overrides[get_current_user] = lambda: {"role": role}
            self.assertEqual(client.get("/jobs").status_code, 403)
        app.dependency_overrides[get_current_user] = lambda: {"role": "dosen"}
        with patch("app.routers.jobs.list_jobs", return_value=[]), patch("app.routers.jobs.get_job", return_value=None):
            self.assertEqual(client.get("/jobs").status_code, 200)
            self.assertEqual(client.get("/jobs/missing").status_code, 404)

    def test_pdf_validation_and_cleanup(self):
        with tempfile.TemporaryDirectory() as directory:
            settings = SimpleNamespace(upload_dir=directory, max_pdf_upload_mb=1)
            with pymupdf.open() as doc:
                doc.new_page()
                valid = doc.tobytes()
            upload = UploadFile(io.BytesIO(valid), filename="../../outside.pdf")
            saved = asyncio.run(_save_pdf(upload, settings))
            self.assertEqual(saved.parent, Path(directory))
            self.assertEqual(saved.read_bytes(), valid)
            saved.unlink()
            for content, status in ((b"", 400), (b"fake pdf", 400), (b"x" * (1024 * 1024 + 1), 413)):
                with self.assertRaises(HTTPException) as caught:
                    asyncio.run(_save_pdf(UploadFile(io.BytesIO(content), filename="x.pdf"), settings))
                self.assertEqual(caught.exception.status_code, status)
                self.assertEqual(list(Path(directory).iterdir()), [])

    def test_upload_body_limit(self):
        app = FastAPI()
        app.add_middleware(UploadLimitMiddleware)

        @app.post("/pdf/extract")
        async def upload(file: UploadFile):
            return {"ok": True}

        with patch("app.upload_limits.get_settings", return_value=SimpleNamespace(max_pdf_upload_mb=1)):
            client = TestClient(app)
            self.assertEqual(client.post("/pdf/extract", files={"file": ("x.pdf", b"x" * (3 * 1024 * 1024))}).status_code, 413)
            self.assertEqual(client.post("/pdf/extract", files={"file": ("x.pdf", b"small")}).status_code, 200)

    def test_upload_without_content_length(self):
        app = FastAPI()
        app.add_middleware(UploadLimitMiddleware)

        @app.post("/pdf/extract")
        async def upload(file: UploadFile):
            return {"ok": True}

        async def request(root_path=""):
            messages = iter([
                {"type": "http.request", "body": b'--test\r\nContent-Disposition: form-data; name="file"; filename="x.pdf"\r\n\r\n', "more_body": True},
                {"type": "http.request", "body": b"x" * (3 * 1024 * 1024), "more_body": False},
            ])
            sent = []

            async def receive():
                return next(messages)

            async def send(message):
                sent.append(message)

            await app({"type": "http", "method": "POST", "path": root_path + "/pdf/extract", "root_path": root_path, "query_string": b"", "headers": [(b"content-type", b"multipart/form-data; boundary=test")], "scheme": "http", "server": ("test", 80)}, receive, send)
            return sent[0]["status"]

        with patch("app.upload_limits.get_settings", return_value=SimpleNamespace(max_pdf_upload_mb=1)):
            self.assertEqual(asyncio.run(request()), 413)
            self.assertEqual(asyncio.run(request("/api")), 413)

    def test_invalid_answers_rejected_before_database(self):
        for answers in ([], [{"soal_id": "a", "teks_jawaban": " "}], [{"soal_id": "a", "teks_jawaban": "x"}] * 2):
            with self.assertRaises(InvalidSubmission):
                submit_ujian(None, "u", "m", "a", answers)

    def test_attempt_questions_and_repeat_submit(self):
        class Result(list):
            def single(self):
                return self[0] if self else None

            def consume(self):
                pass

        class Session:
            status = "dikerjakan"
            writes = 0

            def execute_write(self, callback):
                return callback(self)

            def run(self, query, **params):
                if "RETURN a.status" in query:
                    return Result([{"status": self.status}])
                if "RETURN s.id AS id" in query:
                    return Result([{"id": "q1"}, {"id": "q2"}])
                if "CREATE (j:JawabanUjian" in query:
                    self.writes += 1
                if "SET a.status='menunggu_penilaian'" in query:
                    self.status = "menunggu_penilaian"
                return Result()

        session = Session()
        for ids in (("q1",), ("q1", "foreign")):
            with self.assertRaises(InvalidSubmission):
                submit_ujian(session, "u", "m", "a", [{"soal_id": i, "teks_jawaban": "answer"} for i in ids])
            self.assertEqual(session.writes, 0)
        answers = [{"soal_id": i, "teks_jawaban": "answer"} for i in ("q1", "q2")]
        self.assertTrue(submit_ujian(session, "u", "m", "a", answers))
        self.assertFalse(submit_ujian(session, "u", "m", "a", answers))
        self.assertEqual(session.writes, 2)


if __name__ == "__main__":
    unittest.main()
