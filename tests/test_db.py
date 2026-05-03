"""Tests for db/memory.py — Database (SQLite) + VectorMemory (ChromaDB)."""

from __future__ import annotations
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from db.memory import Database, VectorMemory, CHROMA_COLLECTIONS, _CHROMA_AVAILABLE


def _make_db() -> Database:
    tmp = tempfile.mkdtemp()
    db  = Database(os.path.join(tmp, "test.db"))
    db.connect()
    return db


def _make_vector() -> VectorMemory:
    tmp = tempfile.mkdtemp()
    v   = VectorMemory(os.path.join(tmp, "chroma"))
    v.connect()
    return v


# ── agent_skills ──────────────────────────────────────────────────────────────

class TestAgentSkills(unittest.TestCase):
    def setUp(self):
        self.db = _make_db()

    def tearDown(self):
        self.db.close()

    def test_get_nonexistent_returns_defaults(self):
        skill = self.db.get_skill("Nonexistent")
        self.assertEqual(skill["skill_level"], 0.5)
        self.assertIsNone(skill["system_prompt_override"])

    def test_update_and_retrieve(self):
        self.db.update_skill("Librarian", 0.75, "Always cite policies.")
        skill = self.db.get_skill("Librarian")
        self.assertEqual(skill["skill_level"], 0.75)
        self.assertEqual(skill["system_prompt_override"], "Always cite policies.")

    def test_update_is_upsert(self):
        self.db.update_skill("Accountant", 0.5)
        self.db.update_skill("Accountant", 0.8, "Be concise.")
        skill = self.db.get_skill("Accountant")
        self.assertEqual(skill["skill_level"], 0.8)

    def test_multiple_agents_independent(self):
        self.db.update_skill("Orchestrator", 0.9)
        self.db.update_skill("Librarian",    0.3)
        self.assertEqual(self.db.get_skill("Orchestrator")["skill_level"], 0.9)
        self.assertEqual(self.db.get_skill("Librarian")["skill_level"],    0.3)

    def test_skill_level_boundary_zero(self):
        self.db.update_skill("A", 0.0)
        self.assertEqual(self.db.get_skill("A")["skill_level"], 0.0)

    def test_skill_level_boundary_one(self):
        self.db.update_skill("A", 1.0)
        self.assertEqual(self.db.get_skill("A")["skill_level"], 1.0)


# ── task_history ──────────────────────────────────────────────────────────────

class TestTaskHistory(unittest.TestCase):
    def setUp(self):
        self.db = _make_db()

    def tearDown(self):
        self.db.close()

    def test_log_and_retrieve(self):
        self.db.log_task("format", "Accountant", 100, 0.0003, "claude-haiku")
        rows = self.db.get_task_history(limit=5)
        self.assertGreaterEqual(len(rows), 1)
        latest = rows[0]
        self.assertEqual(latest["task_type"],  "format")
        self.assertEqual(latest["agent_id"],   "Accountant")
        self.assertEqual(latest["tokens_used"], 100)
        self.assertEqual(latest["model_used"], "claude-haiku")

    def test_limit_respected(self):
        for i in range(10):
            self.db.log_task("general", "Orchestrator", i * 10, 0.001 * i)
        rows = self.db.get_task_history(limit=3)
        self.assertEqual(len(rows), 3)

    def test_rows_descending_order(self):
        self.db.log_task("a", "A1", 1, 0.001)
        self.db.log_task("b", "A2", 2, 0.002)
        rows = self.db.get_task_history(limit=2)
        self.assertEqual(rows[0]["task_type"], "b")   # latest first

    def test_no_model_defaults_to_empty(self):
        self.db.log_task("general", "X", 50, 0.001)
        rows = self.db.get_task_history(limit=1)
        # model_used should be empty string or None, not raise
        self.assertIn("model_used", rows[0])

    def test_empty_db_returns_empty_list(self):
        rows = self.db.get_task_history(limit=10)
        self.assertEqual(rows, [])


# ── pending_results ───────────────────────────────────────────────────────────

class TestPendingResults(unittest.TestCase):
    def setUp(self):
        self.db = _make_db()

    def tearDown(self):
        self.db.close()

    def test_add_and_retrieve(self):
        self.db.add_pending_result(0, "Accountant", "Nightly summary done.")
        results = self.db.get_pending_results()
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["agent_id"], "Accountant")
        self.assertEqual(results[0]["delivered"], 0)

    def test_mark_delivered_hides_result(self):
        self.db.add_pending_result(0, "Librarian", "Policy review complete.")
        row_id = self.db.get_pending_results()[0]["id"]
        self.db.mark_delivered(row_id)
        self.assertEqual(self.db.get_pending_results(), [])

    def test_multiple_results(self):
        self.db.add_pending_result(0, "A", "result A")
        self.db.add_pending_result(0, "B", "result B")
        self.assertEqual(len(self.db.get_pending_results()), 2)

    def test_partial_delivery(self):
        self.db.add_pending_result(0, "A", "result A")
        self.db.add_pending_result(0, "B", "result B")
        row_id = self.db.get_pending_results()[0]["id"]
        self.db.mark_delivered(row_id)
        remaining = self.db.get_pending_results()
        self.assertEqual(len(remaining), 1)


# ── scheduled_tasks ───────────────────────────────────────────────────────────

class TestScheduledTasks(unittest.TestCase):
    def setUp(self):
        self.db = _make_db()

    def tearDown(self):
        self.db.close()

    def test_add_and_list(self):
        task_id = self.db.add_scheduled_task("Accountant", "08:00", "Run summary")
        self.assertIsInstance(task_id, int)
        tasks = self.db.get_active_tasks()
        agent_ids = [t["agent_id"] for t in tasks]
        self.assertIn("Accountant", agent_ids)

    def test_multiple_tasks(self):
        self.db.add_scheduled_task("Accountant", "08:00", "Summary")
        self.db.add_scheduled_task("Librarian",  "08:05", "Review")
        self.assertGreaterEqual(len(self.db.get_active_tasks()), 2)

    def test_returns_integer_id(self):
        tid = self.db.add_scheduled_task("X", "@nightly", "payload")
        self.assertIsInstance(tid, int)
        self.assertGreater(tid, 0)


# ── VectorMemory ──────────────────────────────────────────────────────────────

@unittest.skipUnless(_CHROMA_AVAILABLE, "chromadb not installed — run: pip install chromadb")
class TestVectorMemory(unittest.TestCase):
    def setUp(self):
        self.v = _make_vector()

    def test_add_and_query(self):
        self.v.add_document("hr_policies", "test-001", "Remote work allowed 3 days/week.")
        results = self.v.query("hr_policies", "remote work", n_results=1)
        self.assertEqual(len(results), 1)
        self.assertIn("remote", results[0]["text"].lower())

    def test_empty_collection_returns_empty(self):
        results = self.v.query("content_history", "anything", n_results=1)
        self.assertEqual(results, [])

    def test_metadata_preserved(self):
        self.v.add_document(
            "content_history", "post-meta-001",
            "LinkedIn post about AI in HR",
            metadata={"qa_verdict": "PASS", "date": "2025-01-01"},
        )
        # Add a second doc so n_results=1 doesn't exceed collection size edge case
        self.v.add_document(
            "content_history", "post-meta-002",
            "Another LinkedIn post about remote work",
            metadata={"qa_verdict": "FAIL", "date": "2025-01-02"},
        )
        results = self.v.query("content_history", "LinkedIn AI HR", n_results=1)
        self.assertGreater(len(results), 0)
        self.assertIn("qa_verdict", results[0]["meta"])

    def test_unavailable_collection_returns_empty(self):
        results = self.v.query("nonexistent_collection", "query", n_results=1)
        self.assertEqual(results, [])

    def test_connect_creates_all_collections(self):
        for col in CHROMA_COLLECTIONS:
            self.assertIn(col, self.v._collections)

    def test_idempotent_add(self):
        # Adding same ID twice should not raise (ChromaDB upsert by ID)
        self.v.add_document("hr_policies", "dup-001", "First version.")
        self.v.add_document("hr_policies", "dup-001", "Updated version.")
        results = self.v.query("hr_policies", "version", n_results=1)
        self.assertEqual(len(results), 1)


if __name__ == "__main__":
    unittest.main()
