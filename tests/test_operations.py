import importlib.util
import io
import json
from pathlib import Path
import tarfile
import tempfile
import unittest
from unittest.mock import Mock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
from app.readiness import router


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


ROOT = Path(__file__).resolve().parents[2]
ops = load("ops", ROOT / "deploy/ops.py")
secrets_setup = load("secrets_setup", ROOT / "deploy/setup_secrets.py")
admin = load("bootstrap_admin", ROOT / "backend/scripts/bootstrap_admin.py")


class OperationsTests(unittest.TestCase):
    def test_generated_secrets_are_distinct_and_keys_not_interpolated(self):
        template = "DOMAIN=\nGEMINI_API_KEY=\nYOUTUBE_API_KEY=\nPOSTGRES_PASSWORD=\nNEO4J_PASSWORD=\nJWT_SECRET_KEY=\n"
        result = secrets_setup.build_env("math.example.edu", "key$literal", "youtube", template)
        values = dict(line.split("=", 1) for line in result.splitlines())
        self.assertEqual(values["GEMINI_API_KEY"], "'key$literal'")
        self.assertEqual(len({values[k] for k in ("POSTGRES_PASSWORD", "NEO4J_PASSWORD", "JWT_SECRET_KEY")}), 3)
        for bad in ("https://example.edu", "bad\nDOMAIN=other", "localhost"):
            with self.assertRaises(ValueError):
                secrets_setup.build_env(bad, "key", "key", template)

    def test_archive_rejects_traversal_and_symlink(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "backup.tar.gz"
            for name, kind in (("../escape", tarfile.REGTYPE), ("/absolute", tarfile.REGTYPE), ("link", tarfile.SYMTYPE)):
                with tarfile.open(path, "w:gz") as tar:
                    entry = tarfile.TarInfo(name)
                    entry.type = kind
                    tar.addfile(entry)
                with self.assertRaises(ValueError):
                    ops.verify_archive(path)
            with tarfile.open(path, "w:gz") as tar:
                entry = tarfile.TarInfo("./data")
                entry.size = 4
                tar.addfile(entry, io.BytesIO(b"test"))
            ops.verify_archive(path)

    def test_backup_restarts_services_after_archive_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            args = Mock(allow_downtime=True, project="test", directory=tmp, offsite=False)
            calls = [dict(running=True, volume="test", image="sha256:x")] * 3 + [dict(running=False)]
            with patch.object(ops, "run"), patch.object(ops, "inspect_service", side_effect=calls), patch.object(ops, "compose") as compose, patch.object(ops, "archive_volume", side_effect=RuntimeError("disk full")):
                with self.assertRaises(RuntimeError):
                    ops.backup(args)
                compose.assert_any_call("test", "up", "-d")
                self.assertEqual(list(Path(tmp).glob("*/manifest.json")), [])

    def test_readiness_returns_503_without_exception_details(self):
        app = FastAPI()
        app.include_router(router)
        with patch("app.readiness.postgres_connection", side_effect=RuntimeError("secret-password")), patch("app.readiness.neo4j_session", side_effect=RuntimeError("secret-password")):
            response = TestClient(app).get("/ready")
        self.assertEqual(response.status_code, 503)
        self.assertNotIn("secret-password", response.text)

    def test_admin_bootstrap_preserves_existing_admin(self):
        connection = Mock()
        connection.execute.return_value.fetchone.return_value = {"exists": 1}
        with patch.object(admin, "postgres_connection") as factory, patch.object(admin, "hash_password") as hash_password:
            factory.return_value.__enter__.return_value = connection
            self.assertFalse(admin.bootstrap("ADMIN", "Admin", "a sufficiently long password"))
            hash_password.assert_not_called()
