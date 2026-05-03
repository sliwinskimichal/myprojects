"""
Modal dialog screens for Pixel HR Office.

- TaskInputScreen   : user submits a task to a specific agent
- FeedbackScreen    : user provides feedback to trigger improve_skill()
- ContextSelectScreen : user picks an office context
"""

from __future__ import annotations

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Container, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Input, Label, Select, Static


# ── Shared styles ─────────────────────────────────────────────────────────────

_DIALOG_CSS = """
.dialog-box {
    width: 60;
    height: auto;
    background: #0f0f1a;
    border: solid #00FF88;
    padding: 1 2;
    margin: 4 auto;
}
.dialog-title {
    color: #00FF88;
    text-style: bold;
    margin-bottom: 1;
}
.dialog-label {
    color: #aaaacc;
    margin-top: 1;
}
Input {
    margin-top: 0;
    border: solid #1a1a3a;
    background: #080810;
}
Input:focus {
    border: solid #00FF88;
}
Select {
    margin-top: 0;
    border: solid #1a1a3a;
    background: #080810;
}
.btn-row {
    layout: horizontal;
    height: auto;
    margin-top: 1;
    align: right middle;
}
Button {
    margin-left: 1;
}
Button.primary {
    background: #003322;
    color: #00FF88;
    border: solid #00FF88;
}
Button.cancel {
    background: #1a0a0a;
    color: #FF4444;
    border: solid #331111;
}
"""


# ── TaskInputScreen ───────────────────────────────────────────────────────────

AGENT_CHOICES: list[tuple[str, str]] = [
    ("Orchestrator — coordinate & route",  "Orchestrator"),
    ("Accountant — token optimisation",    "Accountant"),
    ("Librarian — knowledge retrieval",    "Librarian"),
    ("Recruiter — build agent team",       "Recruiter"),
    ("CommsExpert — LinkedIn content",     "CommsExpert"),
    ("QA_Critic — quality review",         "QA_Critic"),
    ("Tester — test scenarios",            "Tester"),
    ("Analyst — HR metrics",               "Analyst"),
]


class TaskInputScreen(ModalScreen[dict | None]):
    """Modal: type a task and assign it to an agent."""

    CSS = _DIALOG_CSS

    BINDINGS = [
        Binding("escape", "cancel", "Cancel", show=False),
    ]

    def __init__(self, available_agents: list[str] | None = None) -> None:
        super().__init__()
        self._available_agents = available_agents or [a for _, a in AGENT_CHOICES]

    def compose(self) -> ComposeResult:
        choices = [
            (label, value)
            for label, value in AGENT_CHOICES
            if value in self._available_agents
        ]
        with Vertical(classes="dialog-box"):
            yield Static("◈ NEW TASK", classes="dialog-title")
            yield Label("Task description:", classes="dialog-label")
            yield Input(placeholder="e.g. Write a LinkedIn post about AI in HR…", id="task-input")
            yield Label("Assign to agent:", classes="dialog-label")
            yield Select(choices, id="agent-select", value=choices[0][1] if choices else Select.BLANK)
            with Container(classes="btn-row"):
                yield Button("Run Task", id="btn-run", classes="primary")
                yield Button("Cancel",   id="btn-cancel", classes="cancel")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-run":
            task_input = self.query_one("#task-input", Input)
            agent_select = self.query_one("#agent-select", Select)
            task_text = task_input.value.strip()
            if not task_text:
                task_input.focus()
                return
            self.dismiss({
                "task":   task_text,
                "agent":  str(agent_select.value),
            })
        else:
            self.dismiss(None)

    def action_cancel(self) -> None:
        self.dismiss(None)


# ── FeedbackScreen ────────────────────────────────────────────────────────────

class FeedbackScreen(ModalScreen[dict | None]):
    """Modal: provide feedback on the last agent output → triggers improve_skill."""

    CSS = _DIALOG_CSS

    BINDINGS = [
        Binding("escape", "cancel", "Cancel", show=False),
    ]

    def __init__(self, agent_id: str, last_output: str) -> None:
        super().__init__()
        self._agent_id    = agent_id
        self._last_output = last_output

    def compose(self) -> ComposeResult:
        preview = (self._last_output[:120] + "…") if len(self._last_output) > 120 else self._last_output
        with Vertical(classes="dialog-box"):
            yield Static(f"◈ FEEDBACK → {self._agent_id}", classes="dialog-title")
            yield Label("Last output (preview):", classes="dialog-label")
            yield Static(f"[dim]{preview}[/]")
            yield Label("Your feedback:", classes="dialog-label")
            yield Input(
                placeholder="e.g. Too formal. Should avoid corporate jargon.",
                id="feedback-input",
            )
            with Container(classes="btn-row"):
                yield Button("Submit Feedback", id="btn-submit", classes="primary")
                yield Button("Cancel",          id="btn-cancel", classes="cancel")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-submit":
            feedback_input = self.query_one("#feedback-input", Input)
            feedback = feedback_input.value.strip()
            if not feedback:
                feedback_input.focus()
                return
            self.dismiss({
                "agent_id":    self._agent_id,
                "feedback":    feedback,
                "last_output": self._last_output,
            })
        else:
            self.dismiss(None)

    def action_cancel(self) -> None:
        self.dismiss(None)


# ── ContextSelectScreen ───────────────────────────────────────────────────────

class ContextSelectScreen(ModalScreen[str | None]):
    """Modal: choose the active office context."""

    CSS = _DIALOG_CSS

    BINDINGS = [
        Binding("escape", "cancel", "Cancel", show=False),
    ]

    CONTEXT_CHOICES: list[tuple[str, str]] = [
        ("🏢  HR Office — policies, recruitment, reporting",    "HR_Office"),
        ("💻  Software House — dev, QA, LinkedIn outreach",     "Software_House"),
        ("🚀  Startup — lean team, fast execution",             "Startup"),
    ]

    def __init__(self, current: str) -> None:
        super().__init__()
        self._current = current

    def compose(self) -> ComposeResult:
        with Vertical(classes="dialog-box"):
            yield Static("◈ SWITCH CONTEXT", classes="dialog-title")
            yield Label("Select office context:", classes="dialog-label")
            yield Select(
                self.CONTEXT_CHOICES,
                id="ctx-select",
                value=self._current,
            )
            with Container(classes="btn-row"):
                yield Button("Switch", id="btn-switch", classes="primary")
                yield Button("Cancel", id="btn-cancel", classes="cancel")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-switch":
            sel = self.query_one("#ctx-select", Select)
            self.dismiss(str(sel.value))
        else:
            self.dismiss(None)

    def action_cancel(self) -> None:
        self.dismiss(None)
