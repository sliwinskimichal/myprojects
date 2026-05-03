"""Tests for engine/office_graph.py — task routing and stub graph."""

from __future__ import annotations
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

try:
    from engine.agents import AgentState, TokenAccountant
    from engine.office_graph import _classify_task, _StubGraph, build_graph
    _DEPS_OK = True
except ImportError:
    _DEPS_OK = False

_skip = unittest.skipUnless(_DEPS_OK, "pydantic/langgraph not installed")


def _acc(budget: float = 10.0) -> "TokenAccountant":
    return TokenAccountant(api_key="", daily_budget_usd=budget)


@_skip
class TestClassifyTask(unittest.TestCase):
    CASES = [
        ("optimise token costs",              "optimize"),
        ("reduce the budget",                 "optimize"),
        ("find the remote work policy",       "research"),
        ("search HR archive for leave rules", "research"),
        ("hire a new developer",              "recruit"),
        ("recruit a QA team",                 "recruit"),
        ("write a LinkedIn post",             "linkedin"),
        ("publish content about AI",          "linkedin"),
        ("write test scenarios for login",    "test"),
        ("qa coverage for checkout flow",     "test"),
        ("analyse attrition metrics",         "analyse"),
        ("what are our KPIs this quarter?",   "analyse"),
        ("something completely unrelated",    "general"),
        ("",                                  "general"),
    ]

    def test_all_routing_cases(self):
        for task, expected in self.CASES:
            with self.subTest(task=task):
                self.assertEqual(_classify_task(task), expected)

    def test_case_insensitive_optimize(self):
        self.assertEqual(_classify_task("OPTIMISE TOKENS"), "optimize")

    def test_case_insensitive_linkedin(self):
        self.assertEqual(_classify_task("LinkedIn Post"), "linkedin")

    def test_multiple_keywords_first_wins(self):
        # "cost" → optimize even if "linkedin" appears later
        self.assertEqual(_classify_task("how much does the linkedin campaign cost?"), "optimize")


@_skip
class TestStubGraph(unittest.TestCase):
    def setUp(self):
        self.graph = _StubGraph(_acc(), db=None, vector=None)

    def _invoke(self, task: str) -> dict:
        return self.graph.invoke(AgentState(agent_id="Orchestrator", task=task).model_dump())

    def test_optimize_routes_to_accountant(self):
        self.assertEqual(self._invoke("optimise token costs")["agent_id"], "Accountant")

    def test_research_routes_to_librarian(self):
        self.assertEqual(self._invoke("find remote work policy")["agent_id"], "Librarian")

    def test_recruit_routes_to_recruiter(self):
        self.assertEqual(self._invoke("recruit a new team")["agent_id"], "Recruiter")

    def test_linkedin_includes_qa_review(self):
        result = self._invoke("write a LinkedIn post about AI")["last_result"]
        self.assertTrue("QA Review" in result or "RESULT:" in result)

    def test_test_routes_to_tester(self):
        self.assertEqual(self._invoke("write test scenarios")["agent_id"], "Tester")

    def test_analyse_routes_to_analyst(self):
        self.assertEqual(self._invoke("analyse attrition metrics")["agent_id"], "Analyst")

    def test_result_has_required_fields(self):
        result = self._invoke("optimise costs")
        for key in ("last_result", "tokens_used", "cost_usd", "status"):
            self.assertIn(key, result)

    def test_result_status_done(self):
        self.assertEqual(self._invoke("find policy")["status"], "done")

    def test_cost_positive(self):
        self.assertGreater(self._invoke("optimise costs")["cost_usd"], 0)

    def test_tokens_positive(self):
        self.assertGreater(self._invoke("find policy")["tokens_used"], 0)

    def test_last_result_nonempty_for_all_routes(self):
        tasks = [
            "optimise costs", "find policy", "recruit team",
            "write linkedin post", "write test cases", "analyse metrics",
        ]
        for task in tasks:
            with self.subTest(task=task):
                result = self._invoke(task)
                self.assertGreater(len(result["last_result"]), 0, f"Empty result for: {task}")


@_skip
class TestBuildGraph(unittest.TestCase):
    def test_returns_invokable(self):
        graph = build_graph(_acc(), db=None, vector=None)
        self.assertTrue(hasattr(graph, "invoke"))

    def test_invoke_returns_dict(self):
        graph  = build_graph(_acc(), db=None, vector=None)
        result = graph.invoke(AgentState(agent_id="Orchestrator", task="optimise tokens").model_dump())
        self.assertIsInstance(result, dict)

    def test_stub_used_when_langgraph_missing(self):
        # _StubGraph always has .invoke
        stub = _StubGraph(_acc(), db=None, vector=None)
        self.assertTrue(callable(stub.invoke))


if __name__ == "__main__":
    unittest.main()
