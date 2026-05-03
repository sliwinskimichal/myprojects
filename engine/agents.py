"""Agent definitions: TokenAccountant middleware + AgentState + improve_skill."""

from __future__ import annotations

import re
import time
import logging
from typing import TYPE_CHECKING, Any, Callable, Literal

from pydantic import BaseModel, Field

if TYPE_CHECKING:
    from db.memory import Database

log = logging.getLogger(__name__)

# ── Model IDs ─────────────────────────────────────────────────────────────────

MODEL_SONNET = "claude-sonnet-4-6"
MODEL_HAIKU  = "claude-haiku-4-5-20251001"

_COST_PER_1K: dict[str, float] = {
    MODEL_SONNET: 0.003,
    MODEL_HAIKU:  0.00025,
}

_HAIKU_TASK_KEYWORDS = {"format", "translate", "summarize", "reformat", "classify"}

# ── Structured error types ────────────────────────────────────────────────────

class BudgetExceededError(RuntimeError):
    """Raised when the daily API cost budget is exhausted."""
    def __init__(self, used: float, budget: float) -> None:
        self.used   = used
        self.budget = budget
        super().__init__(
            f"Daily budget cap ${budget:.2f} reached (session: ${used:.4f}). "
            "Increase DAILY_BUDGET_USD or restart."
        )


class APIError(RuntimeError):
    """Wraps transient Anthropic API errors after all retries are exhausted."""
    def __init__(self, original: Exception, attempts: int) -> None:
        self.original = original
        self.attempts = attempts
        super().__init__(f"API call failed after {attempts} attempt(s): {original}")


# ── Mock responses ────────────────────────────────────────────────────────────

_MOCK_RESPONSES: dict[str, str] = {
    "Orchestrator": (
        "Task received. Routing to the appropriate specialist. "
        "I'll coordinate the workflow and consolidate results. "
        "Estimated completion: 2 agent cycles."
    ),
    "Accountant": (
        "Token analysis complete. Current prompt ≈ 147 tokens. "
        "Recommendation: switch to Haiku for this task — "
        "saving ~$0.00042 per call. Projected monthly saving at 1k calls/day: $12.60."
    ),
    "Librarian": (
        "Searching HR policy archive… Found 2 relevant documents. "
        "Policy HR-104: remote work permitted up to 3 days/week with manager approval. "
        "Policy HR-201: equipment reimbursement up to €500/year."
    ),
    "Recruiter": (
        "Team assessment complete. Recommended roster:\n"
        "1. Orchestrator 🤖 — overall coordination\n"
        "2. CommsExpert 🔗 — LinkedIn outreach\n"
        "3. Tester 🐞 — QA coverage\n"
        "4. Accountant 💰 — cost control"
    ),
    "CommsExpert": (
        "LinkedIn post draft:\n\n"
        "We're rethinking how AI supports HR — not replacing humans, "
        "but removing friction so people can focus on people. "
        "Here's what 3 months of AI-assisted recruiting taught us…\n\n"
        "#HRTech #FutureOfWork #AI"
    ),
    "QA_Critic": (
        "RESULT: PASS ✓\n"
        "KEY_ISSUE: The conclusion could be stronger.\n"
        "INSTRUCTION: Always end responses with a clear call-to-action or summary."
    ),
    "Tester": (
        "Test scenarios:\n"
        "TC-01 | Happy path | valid input | submit form | 200 OK\n"
        "TC-02 | Empty input | blank fields | submit | 400 Bad Request\n"
        "TC-03 | Boundary | max-length (4096 chars) | submit | 200 OK\n"
        "TC-04 | Concurrent | 10 parallel requests | all | no race condition"
    ),
    "Analyst": (
        "HR Metrics Q2:\n"
        "• Attrition: 8.2% (↑1.1% vs Q1 — investigate Engineering)\n"
        "• Time-to-hire: 24 days (↓3 days — improving)\n"
        "• Employee NPS: 67 (→ stable)\n"
        "Recommendation: exit interviews for Engineering leavers."
    ),
    "default": "Task processed. Analysis complete. Results logged to task history.",
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
    error:                  str                                = ""


# ── TokenAccountant ───────────────────────────────────────────────────────────

class TokenAccountant:
    """
    Middleware wrapping every Claude API call.

    Features
    --------
    - Prompt whitespace compression
    - Haiku / Sonnet routing based on task_type
    - Pre-call cost estimate → fires cost_callback for HUD
    - Prompt caching via Anthropic cache_control on system prompts
    - Mock mode (full pre-written responses when API key absent)
    - Daily budget cap — raises BudgetExceededError
    - Exponential backoff retry (up to max_retries) on transient errors
    - SQLite usage logging via db.log_task()
    """

    # Retry configuration
    MAX_RETRIES   = 3
    RETRY_BASE_S  = 2.0   # first wait: 2 s, then 4 s, then 8 s

    def __init__(
        self,
        db: "Database | None" = None,
        api_key: str = "",
        cost_callback: Callable[[str, float, str], None] | None = None,
        daily_budget_usd: float = 1.0,
    ) -> None:
        self.db               = db
        self._api_key         = api_key
        self._client: Any     = None
        self._mock_mode       = not bool(api_key)
        self.cost_callback    = cost_callback
        self.daily_budget_usd = daily_budget_usd
        self._session_cost    = 0.0

    # ── Lazy Anthropic client ─────────────────────────────────────────────────

    def _get_client(self) -> Any:
        if self._client is None:
            import anthropic
            self._client = anthropic.Anthropic(api_key=self._api_key)
        return self._client

    # ── Prompt optimisation ───────────────────────────────────────────────────

    def optimize_prompt(self, prompt: str) -> str:
        lines = [re.sub(r"[ \t]+", " ", line).strip() for line in prompt.splitlines()]
        out: list[str] = []
        prev_blank = False
        for line in lines:
            if line == "":
                if not prev_blank:
                    out.append(line)
                prev_blank = True
            else:
                out.append(line)
                prev_blank = False
        return "\n".join(out).strip()

    def select_model(self, task_type: str) -> str:
        return MODEL_HAIKU if task_type.lower() in _HAIKU_TASK_KEYWORDS else MODEL_SONNET

    @staticmethod
    def _rough_token_count(text: str) -> int:
        return max(1, len(text) // 4)

    def estimate_cost(self, prompt: str, model: str) -> float:
        tokens = self._rough_token_count(prompt)
        return (tokens / 1000) * _COST_PER_1K.get(model, _COST_PER_1K[MODEL_SONNET])

    # ── Mock response ─────────────────────────────────────────────────────────

    def _mock_call(
        self, prompt: str, task_type: str, agent_id: str, model: str, est_cost: float
    ) -> dict[str, Any]:
        content = _MOCK_RESPONSES.get(agent_id, _MOCK_RESPONSES["default"])
        tokens  = self._rough_token_count(prompt) + self._rough_token_count(content)
        cost    = (tokens / 1000) * _COST_PER_1K.get(model, _COST_PER_1K[MODEL_SONNET])
        self._session_cost += cost
        if self.db:
            self.db.log_task(task_type, agent_id, tokens, cost, model + "[mock]")
        return {
            "content": content, "model": model + "[mock]",
            "tokens_used": tokens, "cost_usd": cost, "estimated_cost": est_cost,
        }

    # ── Retry logic ───────────────────────────────────────────────────────────

    def _call_with_retry(self, **kwargs: Any) -> Any:
        """
        Call anthropic.messages.create() with exponential-backoff retry.
        Retries on rate-limit (429) and transient server errors (5xx).
        Raises APIError after MAX_RETRIES exhausted.
        """
        import anthropic

        client  = self._get_client()
        attempt = 0
        last_exc: Exception | None = None

        while attempt < self.MAX_RETRIES:
            try:
                return client.messages.create(**kwargs)
            except anthropic.RateLimitError as exc:
                last_exc = exc
                wait = self.RETRY_BASE_S * (2 ** attempt)
                log.warning("Rate limit hit (attempt %d/%d). Retrying in %.0fs…",
                            attempt + 1, self.MAX_RETRIES, wait)
                time.sleep(wait)
            except anthropic.APIStatusError as exc:
                if exc.status_code and exc.status_code >= 500:
                    last_exc = exc
                    wait = self.RETRY_BASE_S * (2 ** attempt)
                    log.warning("Server error %d (attempt %d/%d). Retrying in %.0fs…",
                                exc.status_code, attempt + 1, self.MAX_RETRIES, wait)
                    time.sleep(wait)
                else:
                    raise   # 4xx client errors are not retried
            except anthropic.APIConnectionError as exc:
                last_exc = exc
                wait = self.RETRY_BASE_S * (2 ** attempt)
                log.warning("Connection error (attempt %d/%d). Retrying in %.0fs…",
                            attempt + 1, self.MAX_RETRIES, wait)
                time.sleep(wait)
            attempt += 1

        raise APIError(last_exc or RuntimeError("unknown"), self.MAX_RETRIES)

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
        Optimise → estimate → (budget check) → call → log.

        Raises
        ------
        BudgetExceededError  : daily cap reached
        APIError             : all retries exhausted
        anthropic.APIError   : non-retryable 4xx client error
        """
        optimised = self.optimize_prompt(prompt)
        model     = self.select_model(task_type)
        est_cost  = self.estimate_cost(optimised, model)

        if self.cost_callback:
            try:
                self.cost_callback(agent_id, est_cost, model)
            except Exception:
                pass   # never let HUD callback crash the worker

        if self._mock_mode:
            return self._mock_call(optimised, task_type, agent_id, model, est_cost)

        if self._session_cost >= self.daily_budget_usd:
            raise BudgetExceededError(self._session_cost, self.daily_budget_usd)

        messages: list[dict[str, Any]] = [{"role": "user", "content": optimised}]
        kwargs: dict[str, Any] = {
            "model": model, "max_tokens": max_tokens, "messages": messages,
        }
        if system:
            kwargs["system"] = [
                {
                    "type": "text",
                    "text": self.optimize_prompt(system),
                    "cache_control": {"type": "ephemeral"},
                }
            ]
            kwargs["betas"] = ["prompt-caching-2024-07-31"]

        response    = self._call_with_retry(**kwargs)
        content     = response.content[0].text
        tokens_used = response.usage.input_tokens + response.usage.output_tokens
        cost_usd    = (tokens_used / 1000) * _COST_PER_1K.get(model, _COST_PER_1K[MODEL_SONNET])

        self._session_cost += cost_usd
        if self.db:
            self.db.log_task(task_type, agent_id, tokens_used, cost_usd, model)

        return {
            "content": content, "model": model,
            "tokens_used": tokens_used, "cost_usd": cost_usd, "estimated_cost": est_cost,
        }

    @property
    def session_stats(self) -> dict[str, Any]:
        return {
            "session_cost":     self._session_cost,
            "budget_remaining": max(0.0, self.daily_budget_usd - self._session_cost),
            "budget_pct":       min(100.0, (self._session_cost / max(self.daily_budget_usd, 1e-9)) * 100),
            "mock_mode":        self._mock_mode,
        }


# ── Self-improving loop ───────────────────────────────────────────────────────

def improve_skill(
    agent_id: str,
    user_feedback: str,
    original_output: str,
    accountant: TokenAccountant,
    db: "Database",
) -> str:
    """QA-Critic call → derive improvement instruction → persist to SQLite."""
    if accountant._mock_mode:
        new_instruction = _MOCK_CRITIC
    else:
        critic_prompt = (
            f"You are a QA Critic. An AI agent produced the following output:\n\n"
            f"OUTPUT:\n{original_output}\n\n"
            f"USER FEEDBACK:\n{user_feedback}\n\n"
            f"Write ONE concise improvement instruction (≤ 120 words) that the agent "
            f"should follow in future. Start with 'Always' or 'Never'."
        )
        result = accountant.call(
            critic_prompt, task_type="format",
            agent_id=agent_id, max_tokens=200,
        )
        new_instruction = result["content"].strip()

    if len(new_instruction) > 500:
        new_instruction = new_instruction[:500]

    skill     = db.get_skill(agent_id)
    new_level = min(1.0, skill["skill_level"] + 0.05)
    db.update_skill(agent_id, new_level, new_instruction)
    return new_instruction
