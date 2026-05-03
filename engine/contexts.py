"""
Context definitions for Pixel HR Office.

A "context" determines which agents are active and what their focus is.
Switching context triggers the Recruiter to reassemble the visible team.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class AgentConfig:
    """Runtime configuration for a single agent within a context."""
    name: str
    emoji: str
    color: str
    home_zone: str
    system_prompt: str
    task_keywords: list[str] = field(default_factory=list)


@dataclass
class OfficeContext:
    name: str
    description: str
    icon: str
    agents: list[AgentConfig]


# ── Agent prompt templates ─────────────────────────────────────────────────────

_BASE_ACCOUNTANT = (
    "You are the Accountant agent. Your sole purpose is to minimise LLM API costs. "
    "Before any recommendation, calculate approximate token usage. "
    "Always prefer the cheapest model that can handle the task. Respond in ≤ 80 words."
)

_BASE_ORCHESTRATOR = (
    "You are the Orchestrator. You coordinate the HR office agents. "
    "Break complex tasks into sub-tasks, assign them to the right specialist, "
    "and synthesise results. Keep responses concise and structured."
)

_BASE_LIBRARIAN = (
    "You are the Librarian. You retrieve and synthesise knowledge from the HR policy archive. "
    "Always cite the source policy when answering. If unsure, say so. Respond in ≤ 100 words."
)

_BASE_RECRUITER = (
    "You are the Recruiter. You assemble the right team of agents for each task context. "
    "Evaluate required skills, propose the best agent composition, and explain each agent's role."
)

_BASE_COMMS = (
    "You are the CommsExpert, specialising in professional LinkedIn content. "
    "Write posts that are authentic, engaging, and show domain expertise. "
    "Avoid buzzwords. Use a conversational but professional tone. Max 250 words per post."
)

_BASE_QA = (
    "You are the QA Critic. You review agent outputs for quality, accuracy, and tone. "
    "Identify specific issues, not vague complaints. Return a structured critique: "
    "PASS/FAIL, key issue (1 sentence), improvement instruction (1 sentence)."
)

_BASE_TESTER = (
    "You are the Tester agent. You write and review test cases for software features. "
    "Focus on edge cases, boundary conditions, and regression risks. "
    "Output test scenarios in a structured format: name, precondition, steps, expected result."
)

_BASE_ANALYST = (
    "You are the Data Analyst. You analyse HR metrics, attrition data, and workforce trends. "
    "Always surface the 3 most important insights. Present numbers clearly. "
    "Flag any data quality issues you spot."
)


# ── Context: HR Office ─────────────────────────────────────────────────────────

HR_OFFICE = OfficeContext(
    name="HR_Office",
    description="Traditional HR operations — policies, recruitment, reporting",
    icon="🏢",
    agents=[
        AgentConfig(
            name="Orchestrator",
            emoji="🤖",
            color="#00FF88",
            home_zone="HRBP_DESK",
            system_prompt=_BASE_ORCHESTRATOR,
            task_keywords=["coordinate", "manage", "plan", "assign"],
        ),
        AgentConfig(
            name="Accountant",
            emoji="💰",
            color="#FFD700",
            home_zone="VAULT",
            system_prompt=_BASE_ACCOUNTANT,
            task_keywords=["cost", "token", "budget", "optimise", "optimize"],
        ),
        AgentConfig(
            name="Librarian",
            emoji="📚",
            color="#00BFFF",
            home_zone="ARCHIVE",
            system_prompt=_BASE_LIBRARIAN,
            task_keywords=["policy", "find", "search", "archive", "knowledge"],
        ),
        AgentConfig(
            name="Recruiter",
            emoji="👥",
            color="#FF69B4",
            home_zone="HR_HALL",
            system_prompt=_BASE_RECRUITER,
            task_keywords=["hire", "recruit", "team", "onboard", "headcount"],
        ),
    ],
)


# ── Context: Software House ────────────────────────────────────────────────────

SOFTWARE_HOUSE = OfficeContext(
    name="Software_House",
    description="Software development team — code, tests, LinkedIn outreach",
    icon="💻",
    agents=[
        AgentConfig(
            name="Orchestrator",
            emoji="🤖",
            color="#00FF88",
            home_zone="HRBP_DESK",
            system_prompt=_BASE_ORCHESTRATOR
            + " Focus on software delivery: sprints, code quality, team velocity.",
            task_keywords=["sprint", "deliver", "feature", "release"],
        ),
        AgentConfig(
            name="Accountant",
            emoji="💰",
            color="#FFD700",
            home_zone="VAULT",
            system_prompt=_BASE_ACCOUNTANT,
            task_keywords=["cost", "budget", "token", "cloud", "infra"],
        ),
        AgentConfig(
            name="CommsExpert",
            emoji="🔗",
            color="#FF8C00",
            home_zone="HR_HALL",
            system_prompt=_BASE_COMMS,
            task_keywords=["linkedin", "post", "publish", "content", "marketing"],
        ),
        AgentConfig(
            name="Tester",
            emoji="🐞",
            color="#9B59B6",
            home_zone="SERVER_ROOM",
            system_prompt=_BASE_TESTER,
            task_keywords=["test", "qa", "bug", "regression", "coverage"],
        ),
        AgentConfig(
            name="QA_Critic",
            emoji="🔬",
            color="#E74C3C",
            home_zone="ARCHIVE",
            system_prompt=_BASE_QA,
            task_keywords=["review", "critique", "quality", "evaluate"],
        ),
    ],
)


# ── Context: Startup ───────────────────────────────────────────────────────────

STARTUP = OfficeContext(
    name="Startup",
    description="Fast-moving startup — lean team, maximum output",
    icon="🚀",
    agents=[
        AgentConfig(
            name="Orchestrator",
            emoji="🤖",
            color="#00FF88",
            home_zone="HRBP_DESK",
            system_prompt=_BASE_ORCHESTRATOR
            + " Move fast. Prioritise ruthlessly. Ship or drop.",
            task_keywords=["ship", "launch", "mvp", "priority"],
        ),
        AgentConfig(
            name="CommsExpert",
            emoji="🔗",
            color="#FF8C00",
            home_zone="HR_HALL",
            system_prompt=_BASE_COMMS
            + " Startup voice: bold, direct, slightly irreverent. Show metrics.",
            task_keywords=["linkedin", "post", "brand", "growth"],
        ),
        AgentConfig(
            name="Recruiter",
            emoji="👥",
            color="#FF69B4",
            home_zone="IDLE_ZONE",
            system_prompt=_BASE_RECRUITER
            + " Startup context: find generalists who can wear many hats.",
            task_keywords=["hire", "generalist", "founder", "team"],
        ),
        AgentConfig(
            name="Analyst",
            emoji="📊",
            color="#2ECC71",
            home_zone="ARCHIVE",
            system_prompt=_BASE_ANALYST,
            task_keywords=["metrics", "data", "kpi", "trend", "report"],
        ),
    ],
)


# ── Registry ───────────────────────────────────────────────────────────────────

ALL_CONTEXTS: dict[str, OfficeContext] = {
    "HR_Office":      HR_OFFICE,
    "Software_House": SOFTWARE_HOUSE,
    "Startup":        STARTUP,
}

CONTEXT_ORDER = ["HR_Office", "Software_House", "Startup"]


def get_context(name: str) -> OfficeContext:
    if name not in ALL_CONTEXTS:
        raise ValueError(f"Unknown context: {name!r}")
    return ALL_CONTEXTS[name]


def next_context(current: str) -> str:
    idx = CONTEXT_ORDER.index(current) if current in CONTEXT_ORDER else 0
    return CONTEXT_ORDER[(idx + 1) % len(CONTEXT_ORDER)]
