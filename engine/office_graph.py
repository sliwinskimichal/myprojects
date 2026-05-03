"""
LangGraph StateGraph for Pixel HR Office.

Topology:
  orchestrator ──► accountant  (task_type == "optimize")
               ──► librarian   (task_type == "research")
               ──► recruiter   (task_type == "recruit")
               ──► END         (task_type == "done")

Each node receives an AgentState, does its work (real API call or stub),
and returns the updated state dict.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from engine.agents import AgentState, TokenAccountant

if TYPE_CHECKING:
    from db.memory import Database

try:
    from langgraph.graph import END, StateGraph
    _LANGGRAPH_AVAILABLE = True
except ImportError:
    _LANGGRAPH_AVAILABLE = False


# ── Node implementations ──────────────────────────────────────────────────────

def _orchestrator_node(state: dict[str, Any]) -> dict[str, Any]:
    """Decide which specialist agent to call next."""
    s = AgentState(**state)
    s.status = "working"
    s.current_zone = "HRBP_DESK"

    task_lower = s.task.lower()
    if any(kw in task_lower for kw in ("cost", "token", "optim", "budget")):
        s.task_type = "optimize"
    elif any(kw in task_lower for kw in ("search", "find", "policy", "archive")):
        s.task_type = "research"
    elif any(kw in task_lower for kw in ("hire", "recruit", "team", "agent")):
        s.task_type = "recruit"
    else:
        s.task_type = "done"

    return s.model_dump()


def _make_accountant_node(accountant: TokenAccountant, db: "Database | None"):
    def accountant_node(state: dict[str, Any]) -> dict[str, Any]:
        s = AgentState(**state)
        s.agent_id = "Accountant"
        s.status = "working"
        s.current_zone = "SERVER_ROOM"

        prompt = (
            f"You are the Accountant, an expert in token optimisation. "
            f"Task: {s.task}\n\n"
            f"Analyse the task and provide a brief cost-optimisation recommendation."
        )
        system = s.system_prompt_override or (
            "You optimise LLM usage costs. Be concise. Respond in ≤ 80 words."
        )
        result = accountant.call(
            prompt,
            task_type="format",
            system=system,
            agent_id=s.agent_id,
            max_tokens=150,
        )
        s.last_result = result["content"]
        s.tokens_used = result["tokens_used"]
        s.cost_usd    = result["cost_usd"]
        s.status      = "done"
        s.current_zone = "VAULT"
        return s.model_dump()

    return accountant_node


def _make_librarian_node(accountant: TokenAccountant, db: "Database | None"):
    def librarian_node(state: dict[str, Any]) -> dict[str, Any]:
        s = AgentState(**state)
        s.agent_id = "Librarian"
        s.status = "working"
        s.current_zone = "ARCHIVE"

        # Optional RAG: query ChromaDB if available
        rag_context = ""
        if db and hasattr(db, "_chroma"):
            hits = db._chroma.query("hr_policies", s.task)
            if hits:
                rag_context = "\n".join(h["text"] for h in hits[:2])

        prompt = (
            f"You are the Librarian, keeper of HR knowledge.\n"
            f"Task: {s.task}\n"
            + (f"Relevant policy excerpts:\n{rag_context}\n" if rag_context else "")
            + "Provide a concise answer based on available knowledge."
        )
        result = accountant.call(
            prompt,
            task_type="general",
            agent_id=s.agent_id,
            max_tokens=256,
        )
        s.last_result = result["content"]
        s.tokens_used = result["tokens_used"]
        s.cost_usd    = result["cost_usd"]
        s.status      = "done"
        return s.model_dump()

    return librarian_node


def _make_recruiter_node(accountant: TokenAccountant, db: "Database | None"):
    def recruiter_node(state: dict[str, Any]) -> dict[str, Any]:
        s = AgentState(**state)
        s.agent_id = "Recruiter"
        s.status = "working"
        s.current_zone = "HR_HALL"

        prompt = (
            f"You are the Recruiter, responsible for assembling the right agent team.\n"
            f"Task: {s.task}\n\n"
            f"Identify which specialist agents are needed and briefly describe each one's role."
        )
        result = accountant.call(
            prompt,
            task_type="general",
            agent_id=s.agent_id,
            max_tokens=200,
        )
        s.last_result = result["content"]
        s.tokens_used = result["tokens_used"]
        s.cost_usd    = result["cost_usd"]
        s.status      = "done"
        return s.model_dump()

    return recruiter_node


# ── Router ────────────────────────────────────────────────────────────────────

def _route_task(state: dict[str, Any]) -> str:
    task_type = state.get("task_type", "done")
    mapping = {
        "optimize": "accountant",
        "research": "librarian",
        "recruit":  "recruiter",
    }
    return mapping.get(task_type, END)  # type: ignore[return-value]


# ── Graph factory ─────────────────────────────────────────────────────────────

def build_graph(
    accountant: TokenAccountant,
    db: "Database | None" = None,
) -> Any:
    """
    Compile and return the LangGraph StateGraph.

    Falls back to a simple stub callable if langgraph is not installed.
    """
    if not _LANGGRAPH_AVAILABLE:
        return _StubGraph(accountant, db)

    graph = StateGraph(dict)

    graph.add_node("orchestrator", _orchestrator_node)
    graph.add_node("accountant",   _make_accountant_node(accountant, db))
    graph.add_node("librarian",    _make_librarian_node(accountant, db))
    graph.add_node("recruiter",    _make_recruiter_node(accountant, db))

    graph.set_entry_point("orchestrator")
    graph.add_conditional_edges(
        "orchestrator",
        _route_task,
        {
            "accountant": "accountant",
            "librarian":  "librarian",
            "recruiter":  "recruiter",
            END:           END,
        },
    )
    for node in ("accountant", "librarian", "recruiter"):
        graph.add_edge(node, END)

    return graph.compile()


# ── Stub fallback (no langgraph installed) ────────────────────────────────────

class _StubGraph:
    """Minimal synchronous stub used when langgraph is not installed."""

    def __init__(self, accountant: TokenAccountant, db: "Database | None") -> None:
        self._accountant = accountant
        self._db = db

    def invoke(self, state: dict[str, Any]) -> dict[str, Any]:
        state = _orchestrator_node(state)
        task_type = state.get("task_type", "done")
        if task_type == "optimize":
            state = _make_accountant_node(self._accountant, self._db)(state)
        elif task_type == "research":
            state = _make_librarian_node(self._accountant, self._db)(state)
        elif task_type == "recruit":
            state = _make_recruiter_node(self._accountant, self._db)(state)
        return state
