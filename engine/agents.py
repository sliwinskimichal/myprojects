"""Agent definitions: TokenAccountant middleware + AgentState + improve_skill."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any, Callable, Literal

from pydantic import BaseModel, Field

if TYPE_CHECKING:
    from db.memory import Database

# ── Model IDs ─────────────────────────────────────────────────────────────────

MODEL_SONNET = "claude-sonnet-4-6"
MODEL_HAIKU  = "claude-haiku-4-5-20251001"

_COST_PER_1K: dict[str, float] = {
    MODEL_SONNET: 0.003,
    MODEL_HAIKU:  0.00025,
}

_HAIKU_TASK_KEYWORDS = {"format", "translate", "summarize", "reformat", "classify"}

# ── Mock responses (used when ANTHROPIC_API_KEY is not set) ───────────────────

_MOCK_RESPONSES: dict[str, str] = {
    "Orchestrator": (
        "Task received. Routing to the appropriate specialist. "
        "I'll coordinate the workflow and consolidate results. "
        "Estimated completion: 2 agent cycles."
    ),
    "Accountant": (
        "Token analysis complete. Current prompt is 147 tokens. "
        "Recommendation: use Haiku model for this task — "
        "saving ~$0.00042 per call. Projected monthly saving at 1k calls/day: $12.60."
    ),
    "Librarian": (
        "Searching HR policy archive… Found 2 relevant documents. "
        "Policy HR-104 states: remote work is permitted up to 3 days/week "
        "with manager approval. Policy HR-201 covers equipment reimbursement."
    ),
    "Recruiter": (
        "Team assessment complete. For this context I recommend: "
        "1x CommsExpert (LinkedIn outreach), 1x Tester (QA coverage), "
        "1x Accountant (cost control). Orchestrator will coordinate."
    ),
    "CommsExpert": (
        "LinkedIn post draft:\n\n"
        "We're rethinking how AI supports HR — not replacing humans, "
        "but removing the friction so people can focus on people. "
        "Here's what we've learned in 3 months of running AI-assisted recruiting…\n\n"
        "#HRTech #FutureOfWork #AI"
    ),
    "QA_Critic": (
        "RESULT: PASS ✓\n"
        "Quality assessment: The output is clear and on-topic. "
        "Minor note: the conclusion could be stronger. "
        "Instruction: Always end responses with a clear call-to-action or summary statement."
    ),
    "Tester": (
        "Test scenarios generated:\n"
        "TC-01: Happy path — valid input, expect 200 OK\n"
        "TC-02: Empty input — expect 400 Bad Request\n"
        "TC-03: Boundary — max-length input (4096 chars)\n"
        "TC-04: Concurrent requests — race condition check"
    ),
    "Analyst": (
        "HR Metrics Summary (Q2):\n"
        "• Attrition rate: 8.2% (↑1.1% vs Q1 — investigate Engineering dept)\n"
        "• Time-to-hire: 24 days average (↓3 days — good progress)\n"
        "• Employee NPS: 67 (stable)\n"
        "Recommendation: schedule exit interviews for Engineering leavers."
    ),
    "default": (
        "Task processed successfully. Analysis complete. "
        "Results have been logged to the task history."
    ),
}

_MOCK_CRITIC = (
    "Always be more concise and direct. Avoid restating the question before answering. "
    "Lead with the most important information."
)


# ── AgentState ────────────────────────────────────────────────────────────────

class AgentState(BaseModel):
    """Shared state threaded through every LangGraph node."""

    agent_id:               str
    current_zone:           str                                 = "IDLE_ZONE"
    task:                   str                                 = ""
    task_type:              str                                 = "general"
    context:                dict[str, Any]                     = Field(default_factory=dict)
    status: Literal["idle", "working", "moving", "done"]       = "idle"
    skill_level:            float                              = 0.5
    system_prompt_override: str | None                         = None
    last_result:            str                                = ""
    tokens_used:            int                                = 0
    cost_usd:               float                              = 0.0
    estimated_cost:         float                              = 0.0
    model_used:             str                                = MODEL_SONNET


# ── TokenAccountant ───────────────────────────────────────────────────────────

class TokenAccountant:
    """
    Middleware wrapping every Claude API call.

    Features:
    - Prompt whitespace compression
    - Haiku / Sonnet routing based on task type
    - Cost estimation before call (fires cost_callback)
    - Prompt caching via cache_control on system prompts
    - Mock mode when API key is absent
    - SQLite usage logging
    """

    def __init__(
        self,
        db: "Database | None" = None,
        api_key: str | None = None,
        cost_callback: Callable[[str, float, str], None] | None = None,
    ) -> None:
        self.db            = db
        self._api_key      = api_key
        self._client: Any  = None
        self._mock_mode    = not bool(api_key)
        # cost_callback(agent_id, estimated_cost, model_name)
        self.cost_callback = cost_callback

    # ── Lazy client ───────────────────────────────────────────────────────────

    def _get_client(self) -> Any:
        if self._client is None:
            import anthropic
            kwargs: dict[str, Any] = {}
            if self._api_key:
                kwargs["api_key"] = self._api_key
            self._client = anthropic.Anthropic(**kwargs)
        return self._client

    # ── Optimisation ─────────────────────────────────────────────────────────

    def optimize_prompt(self, prompt: str) -> str:
        lines = [re.sub(r"[ \t]+", " ", line).strip() for line in prompt.splitlines()]
        compressed: list[str] = []
        prev_blank = False
        for line in lines:
            if line == "":
                if not prev_blank:
                    compressed.append(line)
                prev_blank = True
            else:
                compressed.append(line)
                prev_blank = False
        return "\n".join(compressed).strip()

    def select_model(self, task_type: str) -> str:
        if task_type.lower() in _HAIKU_TASK_KEYWORDS:
            return MODEL_HAIKU
        return MODEL_SONNET

    @staticmethod
    def _rough_token_count(text: str) -> int:
        return max(1, len(text) // 4)

    def estimate_cost(self, prompt: str, model: str) -> float:
        tokens = self._rough_token_count(prompt)
        return (tokens / 1000) * _COST_PER_1K.get(model, _COST_PER_1K[MODEL_SONNET])

    # ── Mock response ─────────────────────────────────────────────────────────

    def _mock_call(
        self,
        prompt: str,
        task_type: str,
        agent_id: str,
        model: str,
        est_cost: float,
    ) -> dict[str, Any]:
        content = _MOCK_RESPONSES.get(agent_id, _MOCK_RESPONSES["default"])
        tokens_used = self._rough_token_count(prompt) + self._rough_token_count(content)
        cost_usd = (tokens_used / 1000) * _COST_PER_1K.get(model, _COST_PER_1K[MODEL_SONNET])
        if self.db:
            self.db.log_task(task_type, agent_id, tokens_used, cost_usd)
        return {
            "content":        content,
            "model":          model + " [mock]",
            "tokens_used":    tokens_used,
            "cost_usd":       cost_usd,
            "estimated_cost": est_cost,
        }

    # ── Primary call ──────────────────────────────────────────────────────────

    def call(
        self,
        prompt: str,
        task_type: str = "general",
        system: str = "",
        agent_id: str = "unknown",
        max_tokens: int = 1024,
    ) -> dict[str, Any]:
        """
        Optimise → route → (optionally) estimate → call → log.

        Returns: content, model, tokens_used, cost_usd, estimated_cost.
        """
        optimised = self.optimize_prompt(prompt)
        model     = self.select_model(task_type)
        est_cost  = self.estimate_cost(optimised, model)

        # Notify HUD before making the (potentially slow) API call
        if self.cost_callback:
            self.cost_callback(agent_id, est_cost, model)

        if self._mock_mode:
            return self._mock_call(optimised, task_type, agent_id, model, est_cost)

        # ── Real API call ─────────────────────────────────────────────────────
        messages = [{"role": "user", "content": optimised}]
        kwargs: dict[str, Any] = {
            "model":      model,
            "max_tokens": max_tokens,
            "messages":   messages,
        }

        if system:
            clean_system = self.optimize_prompt(system)
            # Add prompt caching on system prompt (reduces cost on repeated calls)
            kwargs["system"] = [
                {
                    "type": "text",
                    "text": clean_system,
                    "cache_control": {"type": "ephemeral"},
                }
            ]
            kwargs.setdefault("betas", [])
            if "prompt-caching-2024-07-31" not in kwargs["betas"]:
                kwargs["betas"] = ["prompt-caching-2024-07-31"]
        else:
            if system:
                kwargs["system"] = self.optimize_prompt(system)

        client   = self._get_client()
        response = client.messages.create(**kwargs)

        content     = response.content[0].text
        tokens_used = response.usage.input_tokens + response.usage.output_tokens
        cost_usd    = (tokens_used / 1000) * _COST_PER_1K.get(model, _COST_PER_1K[MODEL_SONNET])

        if self.db:
            self.db.log_task(task_type, agent_id, tokens_used, cost_usd)

        return {
            "content":        content,
            "model":          model,
            "tokens_used":    tokens_used,
            "cost_usd":       cost_usd,
            "estimated_cost": est_cost,
        }


# ── Self-improving loop ───────────────────────────────────────────────────────

def improve_skill(
    agent_id: str,
    user_feedback: str,
    original_output: str,
    accountant: TokenAccountant,
    db: "Database",
) -> str:
    """
    QA-Critic call → derive improvement instruction → persist to SQLite.
    Returns the new instruction string.
    """
    if accountant._mock_mode:
        new_instruction = _MOCK_CRITIC
    else:
        critic_prompt = (
            f"You are a QA Critic. An AI agent produced the following output:\n\n"
            f"OUTPUT:\n{original_output}\n\n"
            f"USER FEEDBACK:\n{user_feedback}\n\n"
            f"Write ONE concise improvement instruction (≤ 120 words) that the agent "
            f"should follow in future to avoid this problem. Start with 'Always' or 'Never'."
        )
        result = accountant.call(
            critic_prompt,
            task_type="format",
            agent_id=agent_id,
            max_tokens=200,
        )
        new_instruction = result["content"].strip()

    if len(new_instruction) > 500:
        new_instruction = new_instruction[:500]

    skill = db.get_skill(agent_id)
    new_level = min(1.0, skill["skill_level"] + 0.05)
    db.update_skill(agent_id, new_level, new_instruction)
    return new_instruction
