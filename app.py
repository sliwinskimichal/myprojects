"""
Pixel HR Office — main entry point.

Run with:
    python app.py

Key bindings:
    t — new task (modal)
    o — optimise tokens (Accountant)
    r — recruit (Recruiter)
    n — night watch cycle
    c — switch office context
    f — give feedback on last result (improve_skill)
    s — show agent skill levels
    1-4 — focus agent 1-4
    q — quit
"""

from __future__ import annotations

import asyncio
import os
from typing import Any

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Container, Vertical
from textual.geometry import Offset
from textual.message import Message
from textual.widgets import Footer, Header, Log, Static

from ui.office_map import OFFICE_MAP, ZONE_LABELS
from ui.speech_bubble import SpeechBubble
from ui.sprites import AGENT_DEFS, AgentSprite, create_sprites_for
from ui.dialogs import ContextSelectScreen, FeedbackScreen, TaskInputScreen
from db.memory import Database, VectorMemory
from engine.agents import AgentState, TokenAccountant, improve_skill
from engine.contexts import ALL_CONTEXTS, CONTEXT_ORDER, next_context
from engine.office_graph import build_graph

# ── Custom messages ────────────────────────────────────────────────────────────


class TaskCompleted(Message):
    def __init__(
        self, agent_id: str, result: str, cost: float, tokens: int, model: str = ""
    ) -> None:
        super().__init__()
        self.agent_id = agent_id
        self.result   = result
        self.cost     = cost
        self.tokens   = tokens
        self.model    = model


class CostEstimate(Message):
    def __init__(self, agent_id: str, estimated_cost: float, model: str) -> None:
        super().__init__()
        self.agent_id       = agent_id
        self.estimated_cost = estimated_cost
        self.model          = model


class SkillImproved(Message):
    def __init__(self, agent_id: str, instruction: str, new_level: float) -> None:
        super().__init__()
        self.agent_id    = agent_id
        self.instruction = instruction
        self.new_level   = new_level


# ── Main App ──────────────────────────────────────────────────────────────────


class PixelHRApp(App[None]):
    """Pixel HR Office — multi-agent TUI."""

    TITLE = "Pixel HR Office"
    SUB_TITLE = "v0.2"

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

    #context-bar {
        dock: top;
        height: 1;
        background: #0d0d1f;
        color: #666688;
        padding: 0 2;
        content-align: left middle;
    }

    #night-watch-banner {
        background: #1a0a0a;
        color: #FF4444;
        text-style: bold;
        padding: 0 1;
        display: none;
        height: 1;
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
        color: #2a5a3a;
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

    SpeechBubble {
        layer: above;
    }

    /* ── HUD ── */
    #hud {
        dock: right;
        width: 32;
        height: 1fr;
        background: #0b0b18;
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
        height: 1;
    }

    #agent-log {
        height: 1fr;
        border: solid #1a1a3a;
        background: #070710;
        margin-bottom: 1;
    }

    #stats-panel {
        height: auto;
        border: solid #1a1a3a;
        padding: 0 1;
        background: #070710;
        margin-bottom: 1;
    }

    #token-counter {
        color: #FFD700;
        text-style: bold;
    }

    #cost-display {
        color: #00FF88;
    }

    #est-cost-display {
        color: #888800;
        text-style: italic;
    }

    #model-display {
        color: #00BFFF;
        margin-top: 1;
    }

    #roster-panel {
        height: auto;
        border: solid #1a1a3a;
        padding: 0 1;
        background: #070710;
    }

    #roster-title {
        color: #FF69B4;
        text-style: bold;
        margin-bottom: 0;
    }

    Footer {
        background: #0b0b18;
    }

    Header {
        background: #111128;
        color: #00FF88;
    }
    """

    BINDINGS = [
        Binding("q", "quit",          "Quit"),
        Binding("t", "new_task",       "Task"),
        Binding("o", "optimize",       "Optimise"),
        Binding("r", "recruit",        "Recruit"),
        Binding("n", "night_watch",    "Night Watch"),
        Binding("c", "switch_context", "Context"),
        Binding("f", "feedback",       "Feedback"),
        Binding("s", "show_skills",    "Skills"),
        Binding("1", "focus_1", "Agent 1", show=False),
        Binding("2", "focus_2", "Agent 2", show=False),
        Binding("3", "focus_3", "Agent 3", show=False),
        Binding("4", "focus_4", "Agent 4", show=False),
    ]

    def __init__(self) -> None:
        super().__init__()
        self._db        = Database("pixel_hr.db")
        self._vector    = VectorMemory("./chroma_db")
        self._accountant = TokenAccountant(
            db=self._db,
            api_key=os.environ.get("ANTHROPIC_API_KEY"),
            cost_callback=self._on_cost_estimate,
        )
        self._graph          = None
        self._sprites:       dict[str, AgentSprite] = {}
        self._total_tokens   = 0
        self._total_cost     = 0.0
        self._demo_step      = 0
        self._current_context = "HR_Office"
        self._active_agents: list[str] = []
        self._last_results:  dict[str, str] = {}  # agent_id → last result text
        self._bubble_counter = 0

    # ── Composition ───────────────────────────────────────────────────────────

    def compose(self) -> ComposeResult:
        yield Header()

        with Container(id="left-panel"):
            yield Static("", id="context-bar")
            yield Static("", id="night-watch-banner")
            with Container(id="map-container"):
                yield Static(OFFICE_MAP, id="office-map")
                with Container(id="agent-layer"):
                    pass  # sprites added dynamically in on_mount

        with Container(id="hud"):
            yield Static("◈ AGENT LOG", id="hud-title")
            yield Log(id="agent-log", auto_scroll=True)
            with Container(id="stats-panel"):
                yield Static("Tokens: 0",          id="token-counter")
                yield Static("Cost:   $0.00000",   id="cost-display")
                yield Static("Est:    —",           id="est-cost-display")
                yield Static("Model:  —",           id="model-display")
            with Container(id="roster-panel"):
                yield Static("◈ ROSTER", id="roster-title")
                yield Static("", id="roster-list")

        yield Footer()

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    def on_mount(self) -> None:
        self._db.connect()
        self._vector.connect()
        self._graph = build_graph(self._accountant, self._db, self._vector)

        mode = "[mock]" if self._accountant._mock_mode else "[live API]"
        self._log(f"Pixel HR Office online {mode}")

        # Seed some HR policy docs into ChromaDB for Librarian RAG
        self._seed_vector_memory()

        # Load initial context
        self._load_context("HR_Office")

        # Check overnight pending results
        pending = self._db.get_pending_results()
        if pending:
            self._show_banner(
                f"★ Masz {len(pending)} raportów z nocy — naciśnij [N]  ★",
                color="#FF4444",
            )
            for row in pending:
                self._log(f"[Night] {row['agent_id']}: {row['result'][:55]}…")
                self._db.mark_delivered(row["id"])

        # Demo movement loop
        self.set_interval(5.0, self._demo_loop)

    # ── Context management ────────────────────────────────────────────────────

    def _load_context(self, ctx_name: str) -> None:
        ctx = ALL_CONTEXTS[ctx_name]
        self._current_context = ctx_name
        self._active_agents   = [a.name for a in ctx.agents]

        # Remove old sprites
        for sprite in list(self._sprites.values()):
            sprite.remove()
        self._sprites.clear()

        # Mount new sprites into agent-layer
        agent_layer = self.query_one("#agent-layer", Container)
        new_sprites = create_sprites_for(self._active_agents)
        for sprite in new_sprites:
            self._sprites[sprite.agent_name] = sprite
            agent_layer.mount(sprite)

        # Update context bar
        icon = ctx.icon
        try:
            self.query_one("#context-bar", Static).update(
                f" {icon}  {ctx.name.replace('_', ' ')}  —  {ctx.description}"
            )
        except Exception:
            pass

        self._update_roster()
        self._log(f"Context → {ctx.icon} {ctx.name.replace('_', ' ')}")
        self._log(f"Agents: {', '.join(self._active_agents)}")

    # ── Demo animation ────────────────────────────────────────────────────────

    def _demo_loop(self) -> None:
        if len(self._active_agents) < 2:
            return
        agent_zones = [
            ("Orchestrator", "VAULT"),
            ("Accountant",   "SERVER_ROOM"),
            ("Librarian",    "HRBP_DESK"),
            ("Recruiter",    "ARCHIVE"),
            ("CommsExpert",  "ARCHIVE"),
            ("Tester",       "VAULT"),
            ("Orchestrator", "HRBP_DESK"),
            ("Accountant",   "VAULT"),
            ("Librarian",    "ARCHIVE"),
            ("Recruiter",    "HR_HALL"),
            ("CommsExpert",  "HR_HALL"),
            ("Tester",       "SERVER_ROOM"),
        ]
        for agent_name, zone in agent_zones[self._demo_step % len(agent_zones):]:
            if agent_name in self._sprites:
                self._sprites[agent_name].move_to(zone)
                break
        self._demo_step += 1

    # ── Key actions ───────────────────────────────────────────────────────────

    def action_new_task(self) -> None:
        def handle_result(result: dict | None) -> None:
            if not result:
                return
            task   = result["task"]
            target = result["agent"]
            self._log(f"Task submitted to {target}: {task[:50]}…")
            self._dispatch_task(task, target)

        self.push_screen(TaskInputScreen(self._active_agents), handle_result)

    def action_optimize(self) -> None:
        self._dispatch_task(
            "optimise token usage for the current HR report pipeline",
            "Accountant",
        )

    def action_recruit(self) -> None:
        self._dispatch_task(
            "recruit a specialist team for the current office context",
            "Recruiter",
        )

    def action_night_watch(self) -> None:
        self._log("Night Watch: running scheduled tasks…")
        self.run_worker(self._night_watch_worker, thread=True, name="night_watch")

    def action_switch_context(self) -> None:
        def handle_result(ctx: str | None) -> None:
            if ctx and ctx != self._current_context:
                self._load_context(ctx)

        self.push_screen(ContextSelectScreen(self._current_context), handle_result)

    def action_feedback(self) -> None:
        if not self._last_results:
            self._log("No agent output to give feedback on yet.")
            return
        agent_id    = next(reversed(self._last_results))
        last_output = self._last_results[agent_id]

        def handle_result(result: dict | None) -> None:
            if not result:
                return
            self._log(f"Processing feedback for {result['agent_id']}…")
            self.run_worker(
                lambda: self._improve_skill_worker(
                    result["agent_id"],
                    result["feedback"],
                    result["last_output"],
                ),
                thread=True,
                name="improve_skill",
            )

        self.push_screen(FeedbackScreen(agent_id, last_output), handle_result)

    def action_show_skills(self) -> None:
        self._log("── Skill Levels ──")
        for name in self._active_agents:
            skill = self._db.get_skill(name)
            bar = "█" * int(skill["skill_level"] * 10) + "░" * (10 - int(skill["skill_level"] * 10))
            self._log(f"  {name}: [{bar}] {skill['skill_level']:.2f}")

    def action_focus_1(self) -> None:
        self._focus_nth(0)

    def action_focus_2(self) -> None:
        self._focus_nth(1)

    def action_focus_3(self) -> None:
        self._focus_nth(2)

    def action_focus_4(self) -> None:
        self._focus_nth(3)

    # ── Task dispatch ─────────────────────────────────────────────────────────

    def _dispatch_task(self, task: str, target_agent: str) -> None:
        sprite = self._sprites.get(target_agent)
        if sprite:
            # Accountant always goes to Server Room first
            work_zone = "SERVER_ROOM" if target_agent == "Accountant" else sprite.home_zone
            sprite.move_to(work_zone)
            sprite.set_working()

        state = AgentState(
            agent_id=target_agent,
            task=task,
            task_type="general",
        ).model_dump()

        self.run_worker(
            lambda: self._graph_worker(state),
            thread=True,
            name=f"task-{target_agent}",
        )

    # ── Worker functions (sync → run in thread) ───────────────────────────────

    def _graph_worker(self, state: dict[str, Any]) -> None:
        if self._graph is None:
            return
        try:
            result = self._graph.invoke(state)
            self.call_from_thread(
                self.post_message,
                TaskCompleted(
                    agent_id=result.get("agent_id", state.get("agent_id", "?")),
                    result=result.get("last_result", ""),
                    cost=result.get("cost_usd", 0.0),
                    tokens=result.get("tokens_used", 0),
                    model=result.get("model_used", ""),
                ),
            )
        except Exception as exc:
            self.call_from_thread(self._log, f"[ERROR] {exc}")

    def _night_watch_worker(self) -> None:
        tasks = [
            ("Accountant",   "Generate nightly token-usage summary."),
            ("Librarian",    "Review and index any HR policy updates from today."),
            ("Orchestrator", "Prepare morning briefing: top 3 priorities for tomorrow."),
        ]
        for agent_id, task_text in tasks:
            if agent_id not in self._active_agents and agent_id not in self._sprites:
                continue
            state = AgentState(agent_id=agent_id, task=task_text).model_dump()
            try:
                if self._graph:
                    result = self._graph.invoke(state)
                    snippet = result.get("last_result", "")[:100]
                    self._db.add_pending_result(0, agent_id, snippet)
                    self.call_from_thread(
                        self.post_message,
                        TaskCompleted(
                            agent_id=agent_id,
                            result=snippet,
                            cost=result.get("cost_usd", 0.0),
                            tokens=result.get("tokens_used", 0),
                            model=result.get("model_used", ""),
                        ),
                    )
            except Exception as exc:
                self.call_from_thread(self._log, f"[Night ERROR] {agent_id}: {exc}")

    def _improve_skill_worker(
        self, agent_id: str, feedback: str, last_output: str
    ) -> None:
        try:
            instruction = improve_skill(
                agent_id, feedback, last_output, self._accountant, self._db
            )
            skill       = self._db.get_skill(agent_id)
            self.call_from_thread(
                self.post_message,
                SkillImproved(agent_id, instruction, skill["skill_level"]),
            )
        except Exception as exc:
            self.call_from_thread(self._log, f"[Skill ERROR] {exc}")

    # ── Message handlers ──────────────────────────────────────────────────────

    def on_task_completed(self, msg: TaskCompleted) -> None:
        self._total_tokens += msg.tokens
        self._total_cost   += msg.cost

        self._last_results[msg.agent_id] = msg.result

        snippet = (msg.result[:55] + "…") if len(msg.result) > 55 else msg.result
        self._log(f"[{msg.agent_id}] {snippet}")
        if msg.tokens:
            model_tag = f"({msg.model.split('-')[1] if '-' in msg.model else msg.model})" if msg.model else ""
            self._log(f"  ↳ {msg.tokens} tok · ${msg.cost:.5f} {model_tag}")

        self._update_stat("#token-counter", f"Tokens: {self._total_tokens:,}")
        self._update_stat("#cost-display",  f"Cost:   ${self._total_cost:.5f}")
        if msg.model:
            self._update_stat("#model-display", f"Model:  {msg.model}")

        # Speech bubble near the sprite
        self._show_speech_bubble(msg.agent_id, snippet)

        # Return sprite to home zone
        sprite = self._sprites.get(msg.agent_id)
        if sprite:
            sprite.move_to(sprite.home_zone)
            sprite.set_idle(False)

        self._update_roster()

    def on_cost_estimate(self, msg: CostEstimate) -> None:
        model_short = "Haiku" if "haiku" in msg.model.lower() else "Sonnet"
        self._update_stat(
            "#est-cost-display",
            f"Est:    ${msg.estimated_cost:.5f} ({model_short})",
        )
        self._update_stat("#model-display", f"Model:  {model_short}")

    def on_skill_improved(self, msg: SkillImproved) -> None:
        self._log(f"[Skill ↑] {msg.agent_id} → {msg.new_level:.2f}")
        self._log(f"  New instruction: {msg.instruction[:60]}…")
        self._update_roster()

    # ── Cost callback (called from worker thread) ─────────────────────────────

    def _on_cost_estimate(self, agent_id: str, cost: float, model: str) -> None:
        self.call_from_thread(
            self.post_message,
            CostEstimate(agent_id, cost, model),
        )

    # ── Speech bubbles ────────────────────────────────────────────────────────

    def _show_speech_bubble(self, agent_id: str, text: str) -> None:
        sprite = self._sprites.get(agent_id)
        if not sprite:
            return
        agent_layer = self.query_one("#agent-layer", Container)
        _, color, _ = AGENT_DEFS.get(agent_id, ("", "#ffffff", ""))
        self._bubble_counter += 1
        bubble = SpeechBubble(
            text,
            color,
            sprite.current_offset,
            duration=5.0,
            bubble_id=f"bubble-{self._bubble_counter}",
        )
        agent_layer.mount(bubble)

    # ── HUD helpers ───────────────────────────────────────────────────────────

    def _update_stat(self, selector: str, text: str) -> None:
        try:
            self.query_one(selector, Static).update(text)
        except Exception:
            pass

    def _update_roster(self) -> None:
        lines: list[str] = []
        for name in self._active_agents:
            skill = self._db.get_skill(name)
            lvl   = skill["skill_level"]
            bar   = "█" * int(lvl * 5) + "░" * (5 - int(lvl * 5))
            emoji = AGENT_DEFS.get(name, ("?", "", ""))[0]
            lines.append(f"{emoji} {name[:11]:<11} [{bar}]")
        try:
            self.query_one("#roster-list", Static).update("\n".join(lines))
        except Exception:
            pass

    def _show_banner(self, text: str, color: str = "#FF4444") -> None:
        try:
            banner = self.query_one("#night-watch-banner", Static)
            banner.update(f" {text} ")
            banner.styles.color   = color
            banner.styles.display = "block"
            self.set_timer(8.0, lambda: setattr(banner.styles, "display", "none"))
        except Exception:
            pass

    def _log(self, text: str) -> None:
        try:
            self.query_one("#agent-log", Log).write_line(text)
        except Exception:
            pass

    def _focus_nth(self, n: int) -> None:
        if n < len(self._active_agents):
            name   = self._active_agents[n]
            sprite = self._sprites.get(name)
            zone   = ZONE_LABELS.get(sprite.current_zone, "?") if sprite else "?"
            self._log(f"◈ {name} @ {zone}")

    # ── ChromaDB seed ─────────────────────────────────────────────────────────

    def _seed_vector_memory(self) -> None:
        """Insert a few HR policy docs so Librarian RAG has something to query."""
        policies = [
            ("policy-001", "Remote work policy (HR-104): Employees may work remotely up to 3 days/week with manager approval. Core hours are 10:00–16:00 local time."),
            ("policy-002", "Equipment reimbursement (HR-201): Home office equipment up to €500/year is reimbursable with receipt and manager sign-off."),
            ("policy-003", "Annual leave (HR-301): Employees are entitled to 26 days annual leave per year. Minimum 10 consecutive days must be taken in the calendar year."),
            ("policy-004", "Performance review (HR-401): Reviews are conducted bi-annually in June and December. Ratings: Exceeds / Meets / Below expectations."),
        ]
        for doc_id, text in policies:
            try:
                self._vector.add_document("hr_policies", doc_id, text)
            except Exception:
                pass


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    app = PixelHRApp()
    app.run()
