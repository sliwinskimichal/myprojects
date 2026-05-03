"""
LangGraph StateGraph for Pixel HR Office.

Topology:
  orchestrator ──► accountant   (task_type == "optimize")
               ──► librarian    (task_type == "research")
               ──► recruiter    (task_type == "recruit")
               ──► comms_flow   (task_type == "linkedin")
               ──► END          (task_type == "done" / fallback)

comms_flow:   comms_expert ──► qa_critic ──► END
"""

from __future__ import annotations

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
    if db:
        skill = db.get_skill(agent_id)
        override = skill.get("system_prompt_override")
        if override:
            return override
    return default


# ── Node: Orchestrator ────────────────────────────────────────────────────────

def _orchestrator_node(state: dict[str, Any]) -> dict[str, Any]:
    s = AgentState(**state)
    s.status = "working"
    s.current_zone = "HRBP_DESK"

    task_lower = s.task.lower()
    if any(kw in task_lower for kw in ("cost", "token", "optim", "budget", "cheap")):
        s.task_type = "optimize"
    elif any(kw in task_lower for kw in ("policy", "find", "search", "archive", "knowledge")):
        s.task_type = "research"
    elif any(kw in task_lower for kw in ("hire", "recruit", "team", "agent", "staff")):
        s.task_type = "recruit"
    elif any(kw in task_lower for kw in ("linkedin", "post", "publish", "content", "comms")):
        s.task_type = "linkedin"
    else:
        s.task_type = "done"

    return s.model_dump()


def _make_orchestrator_node(accountant: TokenAccountant, db: "Database | None"):
    def node(state: dict[str, Any]) -> dict[str, Any]:
        s = AgentState(**state)
        s.current_zone = "HRBP_DESK"
        s.status = "working"

        task_lower = s.task.lower()
        if any(kw in task_lower for kw in ("cost", "token", "optim", "budget", "cheap")):
            s.task_type = "optimize"
        elif any(kw in task_lower for kw in ("policy", "find", "search", "archive", "knowledge")):
            s.task_type = "research"
        elif any(kw in task_lower for kw in ("hire", "recruit", "team", "agent", "staff")):
            s.task_type = "recruit"
        elif any(kw in task_lower for kw in ("linkedin", "post", "publish", "content", "comms")):
            s.task_type = "linkedin"
        else:
            s.task_type = "general"

        if s.task_type == "general":
            # Let Orchestrator handle it directly via LLM
            system = _system_for(
                "Orchestrator", db,
                "You are the Orchestrator. Coordinate HR office tasks. Be concise."
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
        s.agent_id = "Accountant"
        s.status = "working"
        s.current_zone = "SERVER_ROOM"

        system = _system_for(
            "Accountant", db,
            "You optimise LLM usage costs. Be concise. Respond in ≤ 80 words."
        )
        prompt = (
            f"You are the Accountant, an expert in token optimisation.\n"
            f"Task: {s.task}\n\n"
            f"Analyse and provide a cost-optimisation recommendation."
        )
        result = accountant.call(
            prompt,
            task_type="format",
            system=system,
            agent_id="Accountant",
            max_tokens=150,
        )
        s.last_result = result["content"]
        s.tokens_used = result["tokens_used"]
        s.cost_usd    = result["cost_usd"]
        s.model_used  = result["model"]
        s.status      = "done"
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
        s.agent_id = "Librarian"
        s.status = "working"
        s.current_zone = "ARCHIVE"

        rag_context = ""
        if vector:
            hits = vector.query("hr_policies", s.task, n_results=2)
            if hits:
                rag_context = "\n\n".join(h["text"] for h in hits)

        system = _system_for(
            "Librarian", db,
            "You are the Librarian, keeper of HR knowledge. "
            "Always cite policy references when answering. Respond in ≤ 100 words."
        )
        prompt = (
            f"Task: {s.task}\n"
            + (f"\nRelevant policy excerpts:\n{rag_context}\n" if rag_context else "")
            + "\nProvide a concise, policy-grounded answer."
        )
        result = accountant.call(
            prompt,
            task_type="general",
            system=system,
            agent_id="Librarian",
            max_tokens=256,
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
        s.agent_id = "Recruiter"
        s.status = "working"
        s.current_zone = "HR_HALL"

        system = _system_for(
            "Recruiter", db,
            "You assemble the right team of AI agents. "
            "List each agent's name, emoji, and one-line role."
        )
        prompt = (
            f"Task: {s.task}\n\n"
            f"Which agents are needed? Provide a structured team roster."
        )
        result = accountant.call(
            prompt,
            task_type="general",
            system=system,
            agent_id="Recruiter",
            max_tokens=200,
        )
        s.last_result = result["content"]
        s.tokens_used = result["tokens_used"]
        s.cost_usd    = result["cost_usd"]
        s.model_used  = result["model"]
        s.status      = "done"
        return s.model_dump()

    return node


# ── Node: CommsExpert ─────────────────────────────────────────────────────────

def _make_comms_node(accountant: TokenAccountant, db: "Database | None"):
    def node(state: dict[str, Any]) -> dict[str, Any]:
        s = AgentState(**state)
        s.agent_id = "CommsExpert"
        s.status = "working"
        s.current_zone = "HR_HALL"

        system = _system_for(
            "CommsExpert", db,
            "You are the CommsExpert specialising in LinkedIn content. "
            "Write authentic, engaging posts that show domain expertise. "
            "Avoid buzzwords. Max 250 words."
        )
        prompt = (
            f"Write a LinkedIn post about: {s.task}\n\n"
            f"Format: hook line, 2-3 insight paragraphs, hashtags."
        )
        result = accountant.call(
            prompt,
            task_type="general",
            system=system,
            agent_id="CommsExpert",
            max_tokens=350,
        )
        s.last_result = result["content"]
        s.tokens_used = result["tokens_used"]
        s.cost_usd    = result["cost_usd"]
        s.model_used  = result["model"]
        s.status      = "working"  # still needs QA review
        return s.model_dump()

    return node


# ── Node: QA_Critic ───────────────────────────────────────────────────────────

def _make_qa_critic_node(accountant: TokenAccountant, db: "Database | None"):
    def node(state: dict[str, Any]) -> dict[str, Any]:
        s = AgentState(**state)
        prev_result = s.last_result
        s.agent_id = "QA_Critic"
        s.status = "working"
        s.current_zone = "ARCHIVE"

        system = _system_for(
            "QA_Critic", db,
            "You are the QA Critic. Review the content for quality, accuracy, and tone. "
            "Return: PASS/FAIL, key issue (1 sentence), improvement note (1 sentence)."
        )
        prompt = (
            f"Review this content:\n\n{prev_result}\n\n"
            f"Original task: {s.task}\n\n"
            f"Provide your QA assessment."
        )
        result = accountant.call(
            prompt,
            task_type="format",
            system=system,
            agent_id="QA_Critic",
            max_tokens=150,
        )
        qa_verdict = result["content"]
        s.last_result = f"{prev_result}\n\n── QA Review ──\n{qa_verdict}"
        s.tokens_used += result["tokens_used"]
        s.cost_usd    += result["cost_usd"]
        s.model_used   = result["model"]
        s.status       = "done"
        return s.model_dump()

    return node


# ── Node: Tester ──────────────────────────────────────────────────────────────

def _make_tester_node(accountant: TokenAccountant, db: "Database | None"):
    def node(state: dict[str, Any]) -> dict[str, Any]:
        s = AgentState(**state)
        s.agent_id = "Tester"
        s.status = "working"
        s.current_zone = "SERVER_ROOM"

        system = _system_for(
            "Tester", db,
            "You are the Tester. Write concise test scenarios. "
            "Format: TC-ID: name | precondition | steps | expected result."
        )
        result = accountant.call(
            s.task,
            task_type="general",
            system=system,
            agent_id="Tester",
            max_tokens=300,
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
        s.agent_id = "Analyst"
        s.status = "working"
        s.current_zone = "ARCHIVE"

        system = _system_for(
            "Analyst", db,
            "You are the Data Analyst. Surface the 3 most important HR insights. "
            "Present numbers clearly. Flag data quality issues."
        )
        result = accountant.call(
            s.task,
            task_type="general",
            system=system,
            agent_id="Analyst",
            max_tokens=300,
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
    task_type = state.get("task_type", "done")
    mapping = {
        "optimize":  "accountant",
        "research":  "librarian",
        "recruit":   "recruiter",
        "linkedin":  "comms_expert",
    }
    return mapping.get(task_type, END)  # type: ignore[return-value]


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
    graph.add_node("comms_expert", _make_comms_node(accountant, db))
    graph.add_node("qa_critic",    _make_qa_critic_node(accountant, db))
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
            END:            END,
        },
    )
    # comms → QA review
    graph.add_edge("comms_expert", "qa_critic")
    graph.add_edge("qa_critic", END)

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
        self._accountant = accountant
        self._db = db
        self._vector = vector

    def invoke(self, state: dict[str, Any]) -> dict[str, Any]:
        state = _make_orchestrator_node(self._accountant, self._db)(state)
        task_type = state.get("task_type", "done")
        if task_type == "optimize":
            state = _make_accountant_node(self._accountant, self._db)(state)
        elif task_type == "research":
            state = _make_librarian_node(self._accountant, self._db, self._vector)(state)
        elif task_type == "recruit":
            state = _make_recruiter_node(self._accountant, self._db)(state)
        elif task_type == "linkedin":
            state = _make_comms_node(self._accountant, self._db)(state)
            state = _make_qa_critic_node(self._accountant, self._db)(state)
        return state
