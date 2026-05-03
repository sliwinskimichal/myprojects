"""
Pixel HR Office — main entry point.

Run with:
    python app.py
"""

from __future__ import annotations

import os
from typing import Any

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Container, ScrollableContainer
from textual.message import Message
from textual.widgets import Footer, Header, Log, Static

from ui.office_map import OFFICE_MAP
from ui.sprites import AgentSprite, create_all_sprites
from db.memory import Database, VectorMemory
from engine.agents import AgentState, TokenAccountant
from engine.office_graph import build_graph

# ── Custom messages ────────────────────────────────────────────────────────────

class TaskCompleted(Message):
    def __init__(self, agent_id: str, result: str, cost: float, tokens: int) -> None:
        super().__init__()
        self.agent_id = agent_id
        self.result   = result
        self.cost     = cost
        self.tokens   = tokens


class CostEstimate(Message):
    def __init__(self, agent_id: str, estimated_cost: float, model: str) -> None:
        super().__init__()
        self.agent_id       = agent_id
        self.estimated_cost = estimated_cost
        self.model          = model


class AgentMoved(Message):
    def __init__(self, agent_id: str, zone: str) -> None:
        super().__init__()
        self.agent_id = agent_id
        self.zone     = zone


# ── Main App ──────────────────────────────────────────────────────────────────

class PixelHRApp(App[None]):
    """Pixel HR Office — multi-agent TUI."""

    TITLE = "Pixel HR Office"
    SUB_TITLE = "v0.1 MVP"

    CSS = """
    Screen {
        background: #0a0a0a;
        layout: horizontal;
    }

    #left-panel {
        width: 1fr;
        height: 1fr;
        layout: vertical;
    }

    #map-container {
        width: 1fr;
        height: 1fr;
        position: relative;
        overflow: hidden;
    }

    #office-map {
        width: 1fr;
        height: 1fr;
        color: #3a7a5a;
        background: #0a0a0a;
        padding: 0;
    }

    #agent-layer {
        width: 1fr;
        height: 1fr;
        position: absolute;
        background: transparent;
        layer: above;
    }

    AgentSprite {
        background: transparent;
    }

    #hud {
        dock: right;
        width: 30;
        height: 1fr;
        background: #0f0f1a;
        border-left: solid #1a1a3a;
        layout: vertical;
        padding: 1 1;
    }

    #hud-title {
        color: #00FF88;
        text-style: bold;
        border-bottom: solid #1a1a3a;
        padding-bottom: 1;
        margin-bottom: 1;
    }

    #agent-log {
        height: 1fr;
        border: solid #1a1a3a;
        background: #080810;
        margin-bottom: 1;
    }

    #stats-panel {
        height: auto;
        border: solid #1a1a3a;
        padding: 0 1;
        background: #080810;
    }

    #token-counter {
        color: #FFD700;
        text-style: bold;
    }

    #cost-display {
        color: #00FF88;
    }

    #model-display {
        color: #00BFFF;
        margin-top: 1;
    }

    #zone-display {
        color: #FF69B4;
        margin-top: 1;
    }

    #night-watch-banner {
        background: #1a0a0a;
        color: #FF4444;
        text-style: bold;
        padding: 0 1;
        display: none;
        height: 3;
    }

    Footer {
        background: #0f0f1a;
    }

    Header {
        background: #1a1a2e;
        color: #00FF88;
    }
    """

    BINDINGS = [
        Binding("q",         "quit",          "Quit"),
        Binding("o",         "optimize",      "Optimize"),
        Binding("r",         "recruit",       "Recruit"),
        Binding("n",         "night_watch",   "Night Watch"),
        Binding("1",         "focus_agent_1", "Orchestrator", show=False),
        Binding("2",         "focus_agent_2", "Accountant",   show=False),
        Binding("3",         "focus_agent_3", "Librarian",    show=False),
        Binding("4",         "focus_agent_4", "Recruiter",    show=False),
    ]

    def __init__(self) -> None:
        super().__init__()
        self._db           = Database("pixel_hr.db")
        self._vector       = VectorMemory("./chroma_db")
        self._accountant   = TokenAccountant(
            db=self._db,
            api_key=os.environ.get("ANTHROPIC_API_KEY"),
        )
        self._graph        = None
        self._sprites:    dict[str, AgentSprite] = {}
        self._total_tokens = 0
        self._total_cost   = 0.0
        self._active_model = MODEL_DISPLAY_SONNET
        self._demo_step    = 0

    # ── Composition ───────────────────────────────────────────────────────────

    def compose(self) -> ComposeResult:
        yield Header()

        with Container(id="left-panel"):
            yield Static("", id="night-watch-banner")
            with Container(id="map-container"):
                yield Static(OFFICE_MAP, id="office-map")
                with Container(id="agent-layer"):
                    for sprite in create_all_sprites():
                        self._sprites[sprite.agent_name] = sprite
                        yield sprite

        with Container(id="hud"):
            yield Static("◈ AGENT LOG", id="hud-title")
            yield Log(id="agent-log", auto_scroll=True)
            with Container(id="stats-panel"):
                yield Static("Tokens: 0", id="token-counter")
                yield Static("Cost:   $0.0000", id="cost-display")
                yield Static("Model:  Sonnet", id="model-display")
                yield Static("Zone:   —", id="zone-display")

        yield Footer()

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    def on_mount(self) -> None:
        self._db.connect()
        self._vector.connect()
        self._graph = build_graph(self._accountant, self._db)

        self._log("Pixel HR Office online.")
        self._log("Agents reporting for duty...")

        # Check for overnight pending results
        pending = self._db.get_pending_results()
        if pending:
            self._show_night_watch_banner(len(pending))
            for row in pending:
                self._log(f"[Night Watch] {row['agent_id']}: {row['result'][:60]}…")
                self._db.mark_delivered(row["id"])

        # Kick off demo movement loop
        self.set_interval(4.0, self._demo_loop)

    # ── Demo animation loop ───────────────────────────────────────────────────

    def _demo_loop(self) -> None:
        """Cycle sprites through zones to demonstrate movement."""
        sequences: list[tuple[str, str]] = [
            ("Accountant",   "SERVER_ROOM"),
            ("Orchestrator", "VAULT"),
            ("Librarian",    "HRBP_DESK"),
            ("Recruiter",    "ARCHIVE"),
            ("Accountant",   "VAULT"),
            ("Orchestrator", "HRBP_DESK"),
            ("Librarian",    "ARCHIVE"),
            ("Recruiter",    "HR_HALL"),
        ]
        agent_name, zone = sequences[self._demo_step % len(sequences)]
        self._demo_step += 1

        sprite = self._sprites.get(agent_name)
        if sprite:
            sprite.move_to(zone)
            self._update_zone_display(agent_name, zone)

    # ── Key bindings ──────────────────────────────────────────────────────────

    def action_optimize(self) -> None:
        """Trigger Accountant optimisation task."""
        sprite = self._sprites.get("Accountant")
        if sprite:
            sprite.move_to("SERVER_ROOM")
            sprite.set_working()
        self._log("Accountant: moving to Server Room to optimise tokens…")
        self._update_zone_display("Accountant", "SERVER_ROOM")

        state = AgentState(
            agent_id="Accountant",
            task="optimise token usage for the current HR report pipeline",
            task_type="optimize",
        ).model_dump()
        self.run_worker(self._run_graph(state), thread=True, name="optimise")

    def action_recruit(self) -> None:
        """Trigger Recruiter to build a new agent team."""
        sprite = self._sprites.get("Recruiter")
        if sprite:
            sprite.move_to("HR_HALL")
            sprite.set_working()
        self._log("Recruiter: assembling new agent team…")

        state = AgentState(
            agent_id="Recruiter",
            task="recruit a team for software house context: developer, tester, designer",
            task_type="recruit",
        ).model_dump()
        self.run_worker(self._run_graph(state), thread=True, name="recruit")

    def action_night_watch(self) -> None:
        """Simulate Night Watch cycle: generate overnight report."""
        self._log("Night Watch: running scheduled tasks…")
        self.run_worker(self._run_night_watch(), thread=True, name="night_watch")

    def action_focus_agent_1(self) -> None:
        self._focus_sprite("Orchestrator")

    def action_focus_agent_2(self) -> None:
        self._focus_sprite("Accountant")

    def action_focus_agent_3(self) -> None:
        self._focus_sprite("Librarian")

    def action_focus_agent_4(self) -> None:
        self._focus_sprite("Recruiter")

    # ── Worker coroutines ─────────────────────────────────────────────────────

    async def _run_graph(self, state: dict[str, Any]) -> None:
        if self._graph is None:
            return
        try:
            result = self._graph.invoke(state)
            self.post_message(TaskCompleted(
                agent_id=result.get("agent_id", "unknown"),
                result=result.get("last_result", ""),
                cost=result.get("cost_usd", 0.0),
                tokens=result.get("tokens_used", 0),
            ))
        except Exception as exc:  # noqa: BLE001
            self._log(f"[ERROR] {exc}")

    async def _run_night_watch(self) -> None:
        tasks = [
            ("Accountant",   "Generate nightly token-usage summary."),
            ("Librarian",    "Index new HR policy documents added today."),
            ("Orchestrator", "Prepare morning briefing for the team."),
        ]
        for agent_id, task_text in tasks:
            state = AgentState(
                agent_id=agent_id,
                task=task_text,
                task_type="general",
            ).model_dump()
            try:
                if self._graph:
                    result = self._graph.invoke(state)
                    snippet = result.get("last_result", "")[:80]
                    task_log_id = 0
                    self._db.add_pending_result(task_log_id, agent_id, snippet)
                    self.post_message(TaskCompleted(
                        agent_id=agent_id,
                        result=snippet,
                        cost=result.get("cost_usd", 0.0),
                        tokens=result.get("tokens_used", 0),
                    ))
            except Exception as exc:  # noqa: BLE001
                self._log(f"[Night Watch ERROR] {agent_id}: {exc}")

    # ── Message handlers ──────────────────────────────────────────────────────

    def on_task_completed(self, msg: TaskCompleted) -> None:
        self._total_tokens += msg.tokens
        self._total_cost   += msg.cost

        snippet = (msg.result[:50] + "…") if len(msg.result) > 50 else msg.result
        self._log(f"{msg.agent_id}: {snippet}")
        self._log(f"  ↳ tokens={msg.tokens}  cost=${msg.cost:.5f}")

        self.query_one("#token-counter", Static).update(
            f"Tokens: {self._total_tokens:,}"
        )
        self.query_one("#cost-display", Static).update(
            f"Cost:   ${self._total_cost:.5f}"
        )

        # Return sprite to home zone
        sprite = self._sprites.get(msg.agent_id)
        if sprite:
            sprite.move_to(sprite.home_zone)
            sprite.set_idle(False)

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _log(self, text: str) -> None:
        try:
            log_widget = self.query_one("#agent-log", Log)
            log_widget.write_line(text)
        except Exception:
            pass

    def _update_zone_display(self, agent_name: str, zone: str) -> None:
        from ui.office_map import ZONE_LABELS
        label = ZONE_LABELS.get(zone, zone)
        try:
            self.query_one("#zone-display", Static).update(
                f"Zone:   {agent_name} → {label}"
            )
        except Exception:
            pass

    def _focus_sprite(self, name: str) -> None:
        sprite = self._sprites.get(name)
        if sprite:
            self._log(f"Focusing on {name} @ {sprite.zone_label}")
            self._update_zone_display(name, sprite.current_zone)

    def _show_night_watch_banner(self, count: int) -> None:
        try:
            banner = self.query_one("#night-watch-banner", Static)
            banner.update(
                f"  ★ Accountant: Masz {count} gotowych raportów z nocy! "
                f"Naciśnij [N] aby zobaczyć.  ★"
            )
            banner.styles.display = "block"
            # Auto-hide after 8 seconds
            self.set_timer(8.0, lambda: setattr(banner.styles, "display", "none"))
        except Exception:
            pass


# ── Display constants ─────────────────────────────────────────────────────────

MODEL_DISPLAY_SONNET = "Sonnet 4.6"


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    app = PixelHRApp()
    app.run()
