"""Agent definitions: TokenAccountant middleware + AgentState + improve_skill."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any, Literal

from pydantic import BaseModel, Field

if TYPE_CHECKING:
    from db.memory import Database

# ── Token / cost constants ────────────────────────────────────────────────────

# Model IDs — use latest available Claude models
MODEL_SONNET = "claude-sonnet-4-6"
MODEL_HAIKU  = "claude-haiku-4-5-20251001"

# Approximate input cost per 1 000 tokens (USD)
_COST_PER_1K: dict[str, float] = {
    MODEL_SONNET: 0.003,
    MODEL_HAIKU:  0.00025,
}

# Tasks routed to the cheaper Haiku model
_HAIKU_TASK_KEYWORDS = {"format", "translate", "summarize", "reformat", "classify"}


# ── AgentState ────────────────────────────────────────────────────────────────

class AgentState(BaseModel):
    """Shared state threaded through every LangGraph node."""

    agent_id:              str
    current_zone:          str                                  = "IDLE_ZONE"
    task:                  str                                  = ""
    task_type:             str                                  = "general"
    context:               dict[str, Any]                      = Field(default_factory=dict)
    status: Literal["idle", "working", "moving", "done"]       = "idle"
    skill_level:           float                               = 0.5
    system_prompt_override: str | None                         = None
    last_result:           str                                  = ""
    tokens_used:           int                                  = 0
    cost_usd:              float                               = 0.0


# ── TokenAccountant ───────────────────────────────────────────────────────────

class TokenAccountant:
    """
    Middleware that sits in front of every Claude API call.

    Responsibilities:
    - Strip whitespace to reduce token count
    - Route cheap tasks to Haiku, complex ones to Sonnet
    - Estimate cost before the call (for HUD display)
    - Log actual usage to SQLite after the call
    """

    def __init__(self, db: "Database | None" = None, api_key: str | None = None) -> None:
        self.db = db
        self._api_key = api_key
        self._client: Any = None  # anthropic.Anthropic, lazy-init

    # ── Lazy client ───────────────────────────────────────────────────────────

    def _get_client(self) -> Any:
        if self._client is None:
            import anthropic
            kwargs: dict[str, Any] = {}
            if self._api_key:
                kwargs["api_key"] = self._api_key
            self._client = anthropic.Anthropic(**kwargs)
        return self._client

    # ── Optimisation helpers ──────────────────────────────────────────────────

    def optimize_prompt(self, prompt: str) -> str:
        """Strip redundant whitespace from a prompt string."""
        # Collapse runs of spaces/tabs to a single space per line
        lines = [re.sub(r"[ \t]+", " ", line).strip() for line in prompt.splitlines()]
        # Remove fully blank lines that appear more than once consecutively
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
        """Return Haiku for simple tasks, Sonnet for everything else."""
        if task_type.lower() in _HAIKU_TASK_KEYWORDS:
            return MODEL_HAIKU
        return MODEL_SONNET

    @staticmethod
    def _rough_token_count(text: str) -> int:
        """Approximate token count: ~4 chars per token."""
        return max(1, len(text) // 4)

    def estimate_cost(self, prompt: str, model: str) -> float:
        tokens = self._rough_token_count(prompt)
        return (tokens / 1000) * _COST_PER_1K.get(model, _COST_PER_1K[MODEL_SONNET])

    # ── Primary call interface ────────────────────────────────────────────────

    def call(
        self,
        prompt: str,
        task_type: str = "general",
        system: str = "",
        agent_id: str = "unknown",
        max_tokens: int = 1024,
    ) -> dict[str, Any]:
        """
        Optimise, route, call, and log a single Claude API interaction.

        Returns a dict with keys: content, model, tokens_used, cost_usd, estimated_cost.
        """
        optimised = self.optimize_prompt(prompt)
        model     = self.select_model(task_type)
        est_cost  = self.estimate_cost(optimised, model)

        messages = [{"role": "user", "content": optimised}]
        kwargs: dict[str, Any] = {
            "model":      model,
            "max_tokens": max_tokens,
            "messages":   messages,
        }
        if system:
            kwargs["system"] = self.optimize_prompt(system)

        client = self._get_client()
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
    Use a QA-Critic LLM call to derive an improvement instruction and persist it.

    Returns the new instruction string.
    """
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

    # Hard-cap to avoid excessive token cost in future system prompts
    if len(new_instruction) > 500:
        new_instruction = new_instruction[:500]

    skill = db.get_skill(agent_id)
    # Slightly boost skill level on each feedback iteration (cap at 1.0)
    new_level = min(1.0, skill["skill_level"] + 0.05)

    db.update_skill(agent_id, new_level, new_instruction)
    return new_instruction
