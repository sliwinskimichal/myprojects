"""
LangGraph StateGraph for Pixel HR Office.

Topology:
  orchestrator ──► accountant   (task_type == "optimize")
               ──► librarian    (task_type == "research")
               ──► recruiter    (task_type == "recruit")
               ──► comms_expert (task_type == "linkedin")
               ──► tester       (task_type == "test")
               ──► analyst      (task_type == "analyse")
               ──► END          (task_type == "done")

comms_expert ──► qa_critic ──► END  (LinkedIn QA pipeline)
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

from engine.agents import AgentState, TokenAccountant

if TYPE_CHECKING:
    from db.memory import Database, VectorMemory

try:
    from langgraph.graph import END, StateGraph
    _LANGGRAPH_AVAILABLE = True
except ImportError:
    _LANGGRAPH_AVAILABLE = False


# ── Helper: load per-agent system prompt ──────────────────────────────────────

def _system_for(agent_id: str, db: "Database | None", default: str) -> str:
    """Return SQLite system_prompt_override if set, else default."""
    if db:
        skill    = db.get_skill(agent_id)
        override = skill.get("system_prompt_override")
        if override:
            return override
    return default


# ── Helper: store LinkedIn post in ChromaDB content_history ───────────────────

def _store_content(text: str, task: str, qa_verdict: str, vector: "VectorMemory | None") -> None:
    if not vector:
        return
    try:
        doc_id = f"post-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}-{uuid.uuid4().hex[:6]}"
        vector.add_document(
            "content_history",
            doc_id,
            text,
            metadata={"task": task[:120], "qa_verdict": qa_verdict[:80], "date": datetime.now(timezone.utc).isoformat()},
        )
    except Exception:
        pass


# ── Node: Orchestrator ────────────────────────────────────────────────────────

# Routing keywords → task_type
_ROUTE_MAP: list[tuple[list[str], str]] = [
    (["cost", "token", "optim", "budget", "cheap", "expensive"], "optimize"),
    (["policy", "find", "search", "archive", "knowledge", "rule", "hr-1", "hr-2", "hr-3", "hr-4"], "research"),
    (["hire", "recruit", "team", "agent", "staff", "onboard", "headcount"], "recruit"),
    (["linkedin", "post", "publish", "content", "comms", "article", "write"], "linkedin"),
    (["test", "qa", "bug", "regression", "coverage", "scenario", "tdd"], "test"),
    (["metric", "data", "kpi", "trend", "analyse", "analyze", "report", "dashboard"], "analyse"),
]


def _classify_task(task: str) -> str:
    task_lower = task.lower()
    for keywords, task_type in _ROUTE_MAP:
        if any(kw in task_lower for kw in keywords):
            return task_type
    return "general"


def _make_orchestrator_node(accountant: TokenAccountant, db: "Database | None"):
    def node(state: dict[str, Any]) -> dict[str, Any]:
        s = AgentState(**state)
        s.current_zone = "HRBP_DESK"
        s.status = "working"
        s.task_type = _classify_task(s.task)

        # Store routing decision in context for observability
        s.context["routing_decision"] = s.task_type

        if s.task_type == "general":
            system = _system_for(
                "Orchestrator", db,
                "You are the Orchestrator. Coordinate HR office operations. "
                "Be decisive and concise. Always end with a clear next action."
            )
            result = accountant.call(
                s.task,
                task_type="general",
                system=system,
                agent_id="Orchestrator",
                max_tokens=256,
            )
            s.last_result = result["content"]
            s.tokens_used = result["tokens_used"]
            s.cost_usd    = result["cost_usd"]
            s.model_used  = result["model"]
            s.task_type   = "done"

        return s.model_dump()
    return node


# ── Node: Accountant ──────────────────────────────────────────────────────────

def _make_accountant_node(accountant: TokenAccountant, db: "Database | None"):
    def node(state: dict[str, Any]) -> dict[str, Any]:
        s = AgentState(**state)
        s.agent_id     = "Accountant"
        s.status       = "working"
        s.current_zone = "SERVER_ROOM"

        system = _system_for(
            "Accountant", db,
            "You optimise LLM API costs. Always show: current token estimate, "
            "recommended model, and projected monthly saving. Respond in ≤ 100 words."
        )
        prompt = (
            f"Task: {s.task}\n\n"
            f"Analyse token usage and provide a cost-optimisation recommendation."
        )
        result = accountant.call(
            prompt, task_type="format", system=system,
            agent_id="Accountant", max_tokens=160,
        )
        s.last_result  = result["content"]
        s.tokens_used  = result["tokens_used"]
        s.cost_usd     = result["cost_usd"]
        s.model_used   = result["model"]
        s.status       = "done"
        s.current_zone = "VAULT"
        return s.model_dump()
    return node


# ── Node: Librarian ───────────────────────────────────────────────────────────

def _make_librarian_node(
    accountant: TokenAccountant,
    db: "Database | None",
    vector: "VectorMemory | None" = None,
):
    def node(state: dict[str, Any]) -> dict[str, Any]:
        s = AgentState(**state)
        s.agent_id     = "Librarian"
        s.status       = "working"
        s.current_zone = "ARCHIVE"

        # RAG: query hr_policies
        rag_context = ""
        if vector:
            hits = vector.query("hr_policies", s.task, n_results=3)
            if hits:
                rag_context = "\n\n".join(f"• {h['text']}" for h in hits)

        # Also query content_history for context
        style_context = ""
        if vector:
            style_hits = vector.query("persona_templates", "librarian persona", n_results=1)
            if style_hits:
                style_context = style_hits[0]["text"]

        system = _system_for(
            "Librarian", db,
            "You are the Librarian. Retrieve and synthesise HR knowledge. "
            "Cite policy codes (e.g. HR-104) when available. "
            + (f"Persona: {style_context}" if style_context else "")
            + " Respond in ≤ 120 words."
        )
        prompt = (
            f"Query: {s.task}\n"
            + (f"\nRelevant policy excerpts:\n{rag_context}\n" if rag_context else "")
            + "\nProvide a policy-grounded answer."
        )
        result = accountant.call(
            prompt, task_type="general", system=system,
            agent_id="Librarian", max_tokens=256,
        )
        s.last_result = result["content"]
        s.tokens_used = result["tokens_used"]
        s.cost_usd    = result["cost_usd"]
        s.model_used  = result["model"]
        s.status      = "done"
        return s.model_dump()
    return node


# ── Node: Recruiter ───────────────────────────────────────────────────────────

def _make_recruiter_node(accountant: TokenAccountant, db: "Database | None"):
    def node(state: dict[str, Any]) -> dict[str, Any]:
        s = AgentState(**state)
        s.agent_id     = "Recruiter"
        s.status       = "working"
        s.current_zone = "HR_HALL"

        system = _system_for(
            "Recruiter", db,
            "You are the Recruiter. Assemble the optimal AI agent team. "
            "Format your response as a numbered list: AgentName (emoji) — one-line role. "
            "Only include agents from this list: Orchestrator, Accountant, Librarian, "
            "Recruiter, CommsExpert, Tester, QA_Critic, Analyst."
        )
        prompt = (
            f"Context: {s.task}\n\n"
            f"Which agents should be deployed? Provide a structured team roster."
        )
        result = accountant.call(
            prompt, task_type="general", system=system,
            agent_id="Recruiter", max_tokens=220,
        )
        s.last_result = result["content"]
        s.tokens_used = result["tokens_used"]
        s.cost_usd    = result["cost_usd"]
        s.model_used  = result["model"]
        s.status      = "done"
        return s.model_dump()
    return node


# ── Node: CommsExpert ─────────────────────────────────────────────────────────

def _make_comms_node(
    accountant: TokenAccountant,
    db: "Database | None",
    vector: "VectorMemory | None" = None,
):
    def node(state: dict[str, Any]) -> dict[str, Any]:
        s = AgentState(**state)
        s.agent_id     = "CommsExpert"
        s.status       = "working"
        s.current_zone = "HR_HALL"

        # Pull style reference from past high-quality posts
        past_posts = ""
        if vector:
            hits = vector.query("content_history", s.task, n_results=2)
            if hits:
                good = [h for h in hits if "PASS" in h.get("meta", {}).get("qa_verdict", "")]
                if good:
                    past_posts = "\n\n".join(h["text"][:200] for h in good[:1])

        system = _system_for(
            "CommsExpert", db,
            "You are the CommsExpert specialising in LinkedIn content. "
            "Write authentic posts showing domain expertise. Avoid buzzwords. "
            "Structure: attention-grabbing hook, 2-3 insight paragraphs, hashtags. Max 200 words."
            + (f"\n\nStyle reference (past successful post):\n{past_posts}" if past_posts else "")
        )
        prompt = f"Write a LinkedIn post about: {s.task}"
        result = accountant.call(
            prompt, task_type="general", system=system,
            agent_id="CommsExpert", max_tokens=350,
        )
        s.last_result = result["content"]
        s.tokens_used = result["tokens_used"]
        s.cost_usd    = result["cost_usd"]
        s.model_used  = result["model"]
        s.status      = "working"   # pipeline continues to QA
        return s.model_dump()
    return node


# ── Node: QA_Critic ───────────────────────────────────────────────────────────

def _make_qa_critic_node(
    accountant: TokenAccountant,
    db: "Database | None",
    vector: "VectorMemory | None" = None,
):
    def node(state: dict[str, Any]) -> dict[str, Any]:
        s = AgentState(**state)
        draft         = s.last_result
        s.agent_id    = "QA_Critic"
        s.status      = "working"
        s.current_zone = "ARCHIVE"

        system = _system_for(
            "QA_Critic", db,
            "You are the QA Critic. Review content for quality, accuracy, and tone. "
            "Return exactly: RESULT: PASS or RESULT: FAIL, then KEY_ISSUE: one sentence, "
            "then INSTRUCTION: one actionable improvement sentence."
        )
        prompt = (
            f"Review this LinkedIn post:\n\n{draft}\n\n"
            f"Original task: {s.task}\n\n"
            f"Provide QA assessment."
        )
        result = accountant.call(
            prompt, task_type="format", system=system,
            agent_id="QA_Critic", max_tokens=160,
        )
        qa_verdict = result["content"]

        # Store post in content_history regardless of pass/fail
        _store_content(draft, s.task, qa_verdict, vector)

        s.last_result  = f"{draft}\n\n─── QA Review ───\n{qa_verdict}"
        s.tokens_used += result["tokens_used"]
        s.cost_usd    += result["cost_usd"]
        s.model_used   = result["model"]
        s.status       = "done"
        s.context["qa_verdict"] = qa_verdict
        return s.model_dump()
    return node


# ── Node: Tester ──────────────────────────────────────────────────────────────

def _make_tester_node(accountant: TokenAccountant, db: "Database | None"):
    def node(state: dict[str, Any]) -> dict[str, Any]:
        s = AgentState(**state)
        s.agent_id     = "Tester"
        s.status       = "working"
        s.current_zone = "SERVER_ROOM"

        system = _system_for(
            "Tester", db,
            "You are the Tester. Write concise, structured test scenarios. "
            "Format each as: TC-ID | Name | Precondition | Steps | Expected Result. "
            "Cover happy path, edge cases, and one negative test."
        )
        result = accountant.call(
            s.task, task_type="general", system=system,
            agent_id="Tester", max_tokens=320,
        )
        s.last_result = result["content"]
        s.tokens_used = result["tokens_used"]
        s.cost_usd    = result["cost_usd"]
        s.model_used  = result["model"]
        s.status      = "done"
        return s.model_dump()
    return node


# ── Node: Analyst ─────────────────────────────────────────────────────────────

def _make_analyst_node(accountant: TokenAccountant, db: "Database | None"):
    def node(state: dict[str, Any]) -> dict[str, Any]:
        s = AgentState(**state)
        s.agent_id     = "Analyst"
        s.status       = "working"
        s.current_zone = "ARCHIVE"

        system = _system_for(
            "Analyst", db,
            "You are the Data Analyst. Identify the 3 most important insights. "
            "Present numbers clearly with trend indicators (↑ ↓ →). "
            "Flag data quality issues. Respond in ≤ 150 words."
        )
        result = accountant.call(
            s.task, task_type="general", system=system,
            agent_id="Analyst", max_tokens=300,
        )
        s.last_result = result["content"]
        s.tokens_used = result["tokens_used"]
        s.cost_usd    = result["cost_usd"]
        s.model_used  = result["model"]
        s.status      = "done"
        return s.model_dump()
    return node


# ── Router ────────────────────────────────────────────────────────────────────

def _route_after_orchestrator(state: dict[str, Any]) -> str:
    routing = {
        "optimize":  "accountant",
        "research":  "librarian",
        "recruit":   "recruiter",
        "linkedin":  "comms_expert",
        "test":      "tester",
        "analyse":   "analyst",
    }
    return routing.get(state.get("task_type", "done"), END)  # type: ignore[return-value]


# ── Graph factory ─────────────────────────────────────────────────────────────

def build_graph(
    accountant: TokenAccountant,
    db: "Database | None" = None,
    vector: "VectorMemory | None" = None,
) -> Any:
    if not _LANGGRAPH_AVAILABLE:
        return _StubGraph(accountant, db, vector)

    graph = StateGraph(dict)

    graph.add_node("orchestrator", _make_orchestrator_node(accountant, db))
    graph.add_node("accountant",   _make_accountant_node(accountant, db))
    graph.add_node("librarian",    _make_librarian_node(accountant, db, vector))
    graph.add_node("recruiter",    _make_recruiter_node(accountant, db))
    graph.add_node("comms_expert", _make_comms_node(accountant, db, vector))
    graph.add_node("qa_critic",    _make_qa_critic_node(accountant, db, vector))
    graph.add_node("tester",       _make_tester_node(accountant, db))
    graph.add_node("analyst",      _make_analyst_node(accountant, db))

    graph.set_entry_point("orchestrator")
    graph.add_conditional_edges(
        "orchestrator",
        _route_after_orchestrator,
        {
            "accountant":  "accountant",
            "librarian":   "librarian",
            "recruiter":   "recruiter",
            "comms_expert":"comms_expert",
            "tester":      "tester",
            "analyst":     "analyst",
            END:            END,
        },
    )

    graph.add_edge("comms_expert", "qa_critic")
    graph.add_edge("qa_critic",    END)

    for node in ("accountant", "librarian", "recruiter", "tester", "analyst"):
        graph.add_edge(node, END)

    return graph.compile()


# ── Stub fallback ─────────────────────────────────────────────────────────────

class _StubGraph:
    def __init__(
        self,
        accountant: TokenAccountant,
        db: "Database | None",
        vector: "VectorMemory | None" = None,
    ) -> None:
        self._a = accountant
        self._db = db
        self._v = vector

    def invoke(self, state: dict[str, Any]) -> dict[str, Any]:
        state     = _make_orchestrator_node(self._a, self._db)(state)
        task_type = state.get("task_type", "done")
        dispatch  = {
            "optimize":  lambda s: _make_accountant_node(self._a, self._db)(s),
            "research":  lambda s: _make_librarian_node(self._a, self._db, self._v)(s),
            "recruit":   lambda s: _make_recruiter_node(self._a, self._db)(s),
            "linkedin":  lambda s: _make_qa_critic_node(self._a, self._db, self._v)(
                _make_comms_node(self._a, self._db, self._v)(s)
            ),
            "test":      lambda s: _make_tester_node(self._a, self._db)(s),
            "analyse":   lambda s: _make_analyst_node(self._a, self._db)(s),
        }
        if task_type in dispatch:
            state = dispatch[task_type](state)
        return state
