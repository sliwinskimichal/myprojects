"""Tests for engine/agents.py — TokenAccountant, AgentState, improve_skill."""

from __future__ import annotations
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

# Graceful skip when pydantic is not installed
try:
    from engine.agents import (
        MODEL_HAIKU, MODEL_SONNET,
        AgentState, BudgetExceededError, TokenAccountant, improve_skill,
    )
    _DEPS_OK = True
except ImportError:
    _DEPS_OK = False

_skip = unittest.skipUnless(_DEPS_OK, "pydantic not installed — run: pip install pydantic")


def _acc(budget: float = 1.0) -> "TokenAccountant":
    return TokenAccountant(api_key="", daily_budget_usd=budget)


@_skip
class TestOptimizePrompt(unittest.TestCase):
    def setUp(self):
        self.acc = _acc()

    def test_collapses_spaces(self):
        self.assertEqual(self.acc.optimize_prompt("hello    world"), "hello world")

    def test_strips_trailing_whitespace(self):
        self.assertEqual(
            self.acc.optimize_prompt("  line one  \n  line two  "),
            "line one\nline two",
        )

    def test_collapses_multiple_blank_lines(self):
        self.assertEqual(self.acc.optimize_prompt("a\n\n\n\nb"), "a\n\nb")

    def test_preserves_single_blank_line(self):
        self.assertEqual(self.acc.optimize_prompt("a\n\nb"), "a\n\nb")

    def test_empty_string(self):
        self.assertEqual(self.acc.optimize_prompt(""), "")


@_skip
class TestSelectModel(unittest.TestCase):
    def setUp(self):
        self.acc = _acc()

    def test_cheap_tasks_use_haiku(self):
        for tt in ["format", "translate", "summarize", "reformat", "classify"]:
            with self.subTest(task_type=tt):
                self.assertEqual(self.acc.select_model(tt), MODEL_HAIKU)

    def test_complex_tasks_use_sonnet(self):
        for tt in ["general", "research", "recruit", "linkedin", "analyse"]:
            with self.subTest(task_type=tt):
                self.assertEqual(self.acc.select_model(tt), MODEL_SONNET)

    def test_case_insensitive_haiku(self):
        self.assertEqual(self.acc.select_model("FORMAT"), MODEL_HAIKU)

    def test_case_insensitive_sonnet(self):
        self.assertEqual(self.acc.select_model("GENERAL"), MODEL_SONNET)


@_skip
class TestEstimateCost(unittest.TestCase):
    def setUp(self):
        self.acc = _acc()

    def test_haiku_cheaper_than_sonnet(self):
        prompt = "a" * 400
        self.assertLess(
            self.acc.estimate_cost(prompt, MODEL_HAIKU),
            self.acc.estimate_cost(prompt, MODEL_SONNET),
        )

    def test_cost_positive(self):
        self.assertGreater(self.acc.estimate_cost("hello", MODEL_SONNET), 0)

    def test_longer_prompt_costs_more(self):
        short = self.acc.estimate_cost("hi", MODEL_SONNET)
        long_ = self.acc.estimate_cost("hi " * 500, MODEL_SONNET)
        self.assertGreater(long_, short)


@_skip
class TestMockCall(unittest.TestCase):
    def setUp(self):
        self.acc = _acc()

    def test_returns_required_keys(self):
        result = self.acc.call("test", agent_id="Accountant")
        for key in ("content", "model", "tokens_used", "cost_usd", "estimated_cost"):
            self.assertIn(key, result)

    def test_mock_flag_in_model_name(self):
        result = self.acc.call("hi", agent_id="Orchestrator")
        self.assertIn("mock", result["model"].lower())

    def test_content_is_nonempty_string(self):
        result = self.acc.call("anything", agent_id="Librarian")
        self.assertIsInstance(result["content"], str)
        self.assertGreater(len(result["content"]), 0)

    def test_session_cost_accumulates(self):
        self.assertEqual(self.acc.session_stats["session_cost"], 0.0)
        self.acc.call("task 1", agent_id="Accountant")
        self.acc.call("task 2", agent_id="Recruiter")
        self.assertGreater(self.acc.session_stats["session_cost"], 0.0)

    def test_unknown_agent_gets_default_response(self):
        result = self.acc.call("anything", agent_id="UnknownBot")
        self.assertIsInstance(result["content"], str)

    def test_cost_callback_fires(self):
        fired = []
        acc = TokenAccountant(
            api_key="",
            daily_budget_usd=1.0,
            cost_callback=lambda aid, cost, model: fired.append((aid, cost, model)),
        )
        acc.call("test", agent_id="Orchestrator")
        self.assertEqual(len(fired), 1)
        self.assertEqual(fired[0][0], "Orchestrator")

    def test_callback_exception_does_not_crash_call(self):
        def bad_cb(*_): raise RuntimeError("cb crash")
        acc = TokenAccountant(api_key="", daily_budget_usd=1.0, cost_callback=bad_cb)
        result = acc.call("test", agent_id="Accountant")   # must not raise
        self.assertTrue(result["content"])


@_skip
class TestBudgetCap(unittest.TestCase):
    def test_budget_exceeded_in_real_mode(self):
        acc = TokenAccountant(api_key="fake-key", daily_budget_usd=0.0)
        with self.assertRaises(BudgetExceededError) as ctx:
            acc.call("test", agent_id="Orchestrator")
        self.assertEqual(ctx.exception.budget, 0.0)

    def test_mock_mode_works_with_zero_budget(self):
        acc = _acc(budget=0.0)
        result = acc.call("test", agent_id="Accountant")
        self.assertTrue(result["content"])

    def test_session_stats_pct_capped_at_100(self):
        acc = _acc()
        acc._session_cost = 999.0
        self.assertEqual(acc.session_stats["budget_pct"], 100.0)

    def test_budget_remaining_never_negative(self):
        acc = _acc()
        acc._session_cost = 999.0
        self.assertEqual(acc.session_stats["budget_remaining"], 0.0)

    def test_budget_exceeded_error_message(self):
        exc = BudgetExceededError(used=1.5, budget=1.0)
        self.assertIn("1.00", str(exc))
        self.assertIn("1.5", str(exc))


@_skip
class TestAgentState(unittest.TestCase):
    def test_default_values(self):
        s = AgentState(agent_id="Orchestrator")
        self.assertEqual(s.current_zone, "IDLE_ZONE")
        self.assertEqual(s.status, "idle")
        self.assertEqual(s.tokens_used, 0)
        self.assertEqual(s.cost_usd, 0.0)
        self.assertEqual(s.error, "")

    def test_model_dump_roundtrip(self):
        s  = AgentState(agent_id="Accountant", task="optimise tokens", task_type="optimize")
        s2 = AgentState(**s.model_dump())
        self.assertEqual(s2.agent_id,  s.agent_id)
        self.assertEqual(s2.task,      s.task)
        self.assertEqual(s2.task_type, s.task_type)

    def test_context_field_is_dict(self):
        self.assertIsInstance(AgentState(agent_id="X").context, dict)

    def test_all_status_literals_valid(self):
        for status in ("idle", "working", "moving", "done"):
            s = AgentState(agent_id="X", status=status)
            self.assertEqual(s.status, status)


@_skip
class TestImproveSkill(unittest.TestCase):
    def _db(self):
        from db.memory import Database
        tmp = tempfile.mkdtemp()
        db  = Database(os.path.join(tmp, "test.db"))
        db.connect()
        return db

    def test_returns_nonempty_string(self):
        result = improve_skill("Librarian", "Too verbose", "Long output.", _acc(), self._db())
        self.assertIsInstance(result, str)
        self.assertGreater(len(result), 0)

    def test_skill_level_increases(self):
        db     = self._db()
        before = db.get_skill("Librarian")["skill_level"]
        improve_skill("Librarian", "Too verbose", "Long output.", _acc(), db)
        self.assertGreater(db.get_skill("Librarian")["skill_level"], before)

    def test_skill_capped_at_1(self):
        db = self._db()
        db.update_skill("Librarian", 0.99)
        improve_skill("Librarian", "feedback", "output", _acc(), db)
        self.assertLessEqual(db.get_skill("Librarian")["skill_level"], 1.0)

    def test_instruction_persisted(self):
        db = self._db()
        improve_skill("Accountant", "Be concise", "verbose output", _acc(), db)
        self.assertIsNotNone(db.get_skill("Accountant")["system_prompt_override"])


if __name__ == "__main__":
    unittest.main()
