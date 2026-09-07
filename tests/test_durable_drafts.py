import copy
import unittest
from contextlib import contextmanager
from unittest.mock import Mock, patch

from app.services import durable_jobs, graph_confirmation, pdf_pipeline, youtube_pipeline


class DraftTests(unittest.TestCase):
    def setUp(self):
        self.row = {"state": "pending", "data": {"value": 1}, "response": None}
        self.conn = Mock()
        self.conn.execute.side_effect = self.execute

    def execute(self, sql, params=None):
        if sql.startswith("SELECT *"):
            return Mock(fetchone=lambda: copy.deepcopy(self.row))
        if "state='confirmed'" in sql:
            self.row.update(state="confirmed", response=params[0].obj)
        if "state='discarded'" in sql:
            self.row["state"] = "discarded"
        return Mock()

    @contextmanager
    def connection(self):
        before = copy.deepcopy(self.row)
        try:
            yield self.conn
        except Exception:
            self.row = before
            raise

    def test_failure_retains_draft_and_retry_returns_cached_response(self):
        with patch.object(durable_jobs, "postgres_connection", self.connection):
            with self.assertRaises(RuntimeError):
                durable_jobs.confirm("j", "pdf", Mock(side_effect=RuntimeError("graph down")))
            self.assertEqual(self.row["state"], "pending")
            write = Mock(return_value={"saved": True})
            self.assertEqual(durable_jobs.confirm("j", "pdf", write), {"saved": True})
            self.assertEqual(durable_jobs.confirm("j", "pdf", write), {"saved": True})
            write.assert_called_once()

    def test_discard_recovers_graph_commit_instead_of_losing_confirmation(self):
        with patch.object(durable_jobs, "postgres_connection", self.connection), patch.object(graph_confirmation, "read_receipt", return_value={"saved": True}):
            self.assertFalse(durable_jobs.discard("j", "pdf"))
            self.assertEqual(self.row["state"], "confirmed")

    def test_discard_is_terminal(self):
        with patch.object(durable_jobs, "postgres_connection", self.connection), patch.object(graph_confirmation, "read_receipt", return_value=None):
            self.assertTrue(durable_jobs.discard("j", "pdf"))
            write = Mock()
            self.assertIsNone(durable_jobs.confirm("j", "pdf", write))
            write.assert_not_called()

    def test_graph_receipt_replay_skips_writes(self):
        tx = Mock()
        tx.run.return_value.single.return_value = {"response": '{"saved": true}'}
        session = Mock()
        session.execute_write.side_effect = lambda fn: fn(tx)
        @contextmanager
        def graph():
            yield session
        with patch.object(graph_confirmation, "neo4j_session", graph):
            write = Mock()
            self.assertEqual(graph_confirmation.apply_once("j", write), {"saved": True})
            write.assert_not_called()

    def test_pdf_writes_all_units_in_supplied_transaction(self):
        tx = Mock()
        units = [{"level": "bab", "bab": "1", "judul": "Bab", "hasil_konsep": [{"nama": "x"}]}]
        result = pdf_pipeline._confirm_pdf(tx, {"modul_id": "m", "nama_domain": "M", "unit_list": units, "unit_final": copy.deepcopy(units)}, {})
        self.assertEqual(result["jumlah_konsep_total"], 1)
        self.assertGreaterEqual(tx.run.call_count, 3)

    def test_youtube_writes_in_supplied_transaction(self):
        video = dict(video_id="v", title="V", channel="C", link="https://youtube.com/watch?v=v", thumbnail="", published_at="")
        tx = Mock()
        result = youtube_pipeline._confirm_youtube(tx, {"video": video, "daftar_konsep": ["X"]}, ["X"])
        self.assertEqual(result["video_id"], "v")
        self.assertEqual(tx.run.call_count, 2)
