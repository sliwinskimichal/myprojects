"""
Pixel HR Office — main entry point.

Run with:
    python app.py

Key bindings:
    t — new task (modal)
    o — optimise tokens (Accountant)
    r — recruit / rebuild team
    n — night watch cycle
    c — switch office context
    f — give feedback on last result (improve_skill)
    s — show agent skill levels
    h — task history + export
    1-4 — focus agent 1-4
    q — quit
"""

from __future__ import annotations

import re
from typing import Any

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Container
from textual.message import Message
from textual.widgets import Footer, Header, Log, Static

from ui.office_map import OFFICE_MAP, ZONE_LABELS
from ui.speech_bubble import SpeechBubble
from ui.sprites import AGENT_DEFS, AgentSprite, create_sprites_for
from ui.dialogs import ContextSelectScreen, FeedbackScreen, TaskInputScreen
from ui.history_screen import HistoryScreen
from db.memory import Database, VectorMemory
from engine.agents import AgentState, BudgetExceededError, TokenAccountant, improve_skill
from engine.config import cfg
from engine.contexts import ALL_CONTEXTS
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


class AgentSpawned(Message):
    def __init__(self, agent_id: str) -> None:
        super().__init__()
        self.agent_id = agent_id


class WorkerError(Message):
    """Carries a structured error from a background worker to the UI thread."""
    def __init__(self, agent_id: str, error: str, is_budget: bool = False) -> None:
        super().__init__()
        self.agent_id  = agent_id
        self.error     = error
        self.is_budget = is_budget


# ── Main App ──────────────────────────────────────────────────────────────────


class PixelHRApp(App[None]):
    """Pixel HR Office — multi-agent TUI."""

    TITLE = "Pixel HR Office"
    SUB_TITLE = "v0.3"

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
        background: #0d0d22;
        color: #5566aa;
        padding: 0 2;
        content-align: left middle;
    }

    #budget-bar {
        height: 1;
        background: #0d1a0d;
        color: #336633;
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

    #budget-display {
        color: #FF8C00;
        margin-top: 1;
    }

    #model-display {
        color: #00BFFF;
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
        Binding("h", "history",        "History"),
        Binding("1", "focus_1", "Agent 1", show=False),
        Binding("2", "focus_2", "Agent 2", show=False),
        Binding("3", "focus_3", "Agent 3", show=False),
        Binding("4", "focus_4", "Agent 4", show=False),
    ]

    def __init__(self) -> None:
        super().__init__()
        self._db        = Database(cfg.db.sqlite_path)
        self._vector    = VectorMemory(cfg.db.chroma_path)
        self._accountant = TokenAccountant(
            db=self._db,
            api_key=cfg.api.anthropic_api_key,
            cost_callback=self._on_cost_estimate,
            daily_budget_usd=cfg.api.daily_budget_usd,
        )
        self._graph           = None
        self._sprites:        dict[str, AgentSprite] = {}
        self._total_tokens    = 0
        self._total_cost      = 0.0
        self._demo_step       = 0
        self._current_context = cfg.app.default_context
        self._active_agents:  list[str] = []
        self._last_results:   dict[str, str] = {}
        self._bubble_counter  = 0

    # ── Composition ───────────────────────────────────────────────────────────

    def compose(self) -> ComposeResult:
        yield Header()

        with Container(id="left-panel"):
            yield Static("", id="context-bar")
            yield Static("", id="budget-bar")
            yield Static("", id="night-watch-banner")
            with Container(id="map-container"):
                yield Static(OFFICE_MAP, id="office-map")
                with Container(id="agent-layer"):
                    pass   # sprites mounted dynamically

        with Container(id="hud"):
            yield Static("◈ AGENT LOG", id="hud-title")
            yield Log(id="agent-log", auto_scroll=True)
            with Container(id="stats-panel"):
                yield Static("Tokens: 0",        id="token-counter")
                yield Static("Cost:   $0.00000", id="cost-display")
                yield Static("Est:    ���",         id="est-cost-display")
                yield Static("Budget: $1.00 rem", id="budget-display")
                yield Static("Model:  —",         id="model-display")
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
        self._seed_vector_memory()

        # Sync HR_Office context prompts to SQLite so graph nodes pick them up
        self._sync_context_to_db("HR_Office")
        self._load_context("HR_Office")

        # Check overnight pending results
        pending = self._db.get_pending_results()
        if pending:
            self._show_banner(
                f"★ Masz {len(pending)} raportów z nocy — [N] aby zobaczyć  ★",
                color="#FF4444",
            )
            for row in pending:
                self._log(f"[Night] {row['agent_id']}: {row['result'][:55]}…")
                self._db.mark_delivered(row["id"])

        self._update_budget_bar()
        self.set_interval(cfg.app.demo_interval, self._demo_loop)
        self.set_interval(15.0, self._update_budget_bar)

    # ── Context management ────────────────────────────────────────────────────

    def _sync_context_to_db(self, ctx_name: str) -> None:
        """Write context agent system prompts to SQLite (used by graph nodes)."""
        ctx = ALL_CONTEXTS[ctx_name]
        for agent_cfg in ctx.agents:
            existing = self._db.get_skill(agent_cfg.name)
            # Only set if there's no user-supplied override yet
            if not existing.get("system_prompt_override"):
                self._db.update_skill(
                    agent_cfg.name,
                    existing.get("skill_level", 0.5),
                    agent_cfg.system_prompt,
                )
        # Seed persona template for Librarian
        try:
            self._vector.add_document(
                "persona_templates",
                f"librarian-{ctx_name}",
                f"Librarian persona for {ctx_name}: formal, policy-driven, cite references.",
            )
        except Exception:
            pass

    def _load_context(self, ctx_name: str) -> None:
        ctx = ALL_CONTEXTS[ctx_name]
        self._current_context = ctx_name
        self._active_agents   = [a.name for a in ctx.agents]

        # Sync fresh system prompts to SQLite (does not overwrite user feedback)
        self._sync_context_to_db(ctx_name)

        # Swap sprites
        for sprite in list(self._sprites.values()):
            sprite.remove()
        self._sprites.clear()

        agent_layer = self.query_one("#agent-layer", Container)
        for sprite in create_sprites_for(self._active_agents):
            self._sprites[sprite.agent_name] = sprite
            agent_layer.mount(sprite)

        # Update context bar
        self._update_stat(
            "#context-bar",
            f" {ctx.icon}  {ctx.name.replace('_', ' ')}  —  {ctx.description}",
        )
        self._update_roster()
        self._log(f"Context → {ctx.icon} {ctx.name.replace('_', ' ')}")
        self._log(f"Roster: {', '.join(self._active_agents)}")

    # ── Dynamic agent spawning ────────────────────────────────────────────────

    def _parse_recruited_agents(self, result_text: str) -> list[str]:
        """Find known agent names mentioned in Recruiter output."""
        found = []
        for name in AGENT_DEFS:
            # Match case-insensitively; also check underscore variant
            pattern = re.compile(re.escape(name.replace("_", " ")), re.IGNORECASE)
            pattern2 = re.compile(re.escape(name), re.IGNORECASE)
            if pattern.search(result_text) or pattern2.search(result_text):
                found.append(name)
        return [n for n in found if n not in self._sprites]

    def _spawn_agent(self, agent_id: str) -> None:
        if agent_id in self._sprites or agent_id not in AGENT_DEFS:
            return
        emoji, color, home_zone = AGENT_DEFS[agent_id]
        sprite = AgentSprite(agent_id, emoji, color, home_zone)
        agent_layer = self.query_one("#agent-layer", Container)
        agent_layer.mount(sprite)
        self._sprites[agent_id] = sprite
        if agent_id not in self._active_agents:
            self._active_agents.append(agent_id)
        # Start in IDLE_ZONE then walk home
        sprite.move_to("IDLE_ZONE")
        self.set_timer(0.5, lambda: sprite.move_to(home_zone))
        self._show_banner(f"★ NEW AGENT: {emoji} {agent_id} deployed!  ★", color="#00FF88")
        self.post_message(AgentSpawned(agent_id))
        self._update_roster()

    # ── Demo animation ────────────────────────────────────────────────────────

    def _demo_loop(self) -> None:
        if len(self._active_agents) < 2:
            return
        all_moves: list[tuple[str, str]] = [
            ("Orchestrator", "VAULT"),
            ("Accountant",   "SERVER_ROOM"),
            ("Librarian",    "HRBP_DESK"),
            ("Recruiter",    "ARCHIVE"),
            ("CommsExpert",  "ARCHIVE"),
            ("Tester",       "VAULT"),
            ("Analyst",      "HR_HALL"),
            ("QA_Critic",    "SERVER_ROOM"),
            ("Orchestrator", "HRBP_DESK"),
            ("Accountant",   "VAULT"),
            ("Librarian",    "ARCHIVE"),
            ("Recruiter",    "HR_HALL"),
            ("CommsExpert",  "HR_HALL"),
            ("Tester",       "SERVER_ROOM"),
        ]
        for agent_name, zone in all_moves[self._demo_step % len(all_moves):]:
            if agent_name in self._sprites:
                self._sprites[agent_name].move_to(zone)
                break
        self._demo_step += 1

    # ── Key actions ───────────────────────────────────────────────────────────

    def action_new_task(self) -> None:
        def handle(result: dict | None) -> None:
            if not result:
                return
            self._log(f"▶ {result['agent']}: {result['task'][:50]}…")
            self._dispatch_task(result["task"], result["agent"])

        self.push_screen(TaskInputScreen(self._active_agents), handle)

    def action_optimize(self) -> None:
        self._dispatch_task(
            "optimise token usage for the current HR operations pipeline — analyse "
            "recent task_history and recommend model switches or prompt compressions",
            "Accountant",
        )

    def action_recruit(self) -> None:
        ctx = ALL_CONTEXTS[self._current_context]
        self._dispatch_task(
            f"Recruit and deploy the optimal specialist team for {ctx.description}",
            "Recruiter",
        )

    def action_night_watch(self) -> None:
        self._log("▶ Night Watch: running scheduled tasks…")
        self.run_worker(self._night_watch_worker, thread=True, name="night_watch")

    def action_switch_context(self) -> None:
        def handle(ctx: str | None) -> None:
            if ctx and ctx != self._current_context:
                self._load_context(ctx)

        self.push_screen(ContextSelectScreen(self._current_context), handle)

    def action_feedback(self) -> None:
        if not self._last_results:
            self._log("No agent output to give feedback on yet.")
            return
        agent_id    = next(reversed(self._last_results))
        last_output = self._last_results[agent_id]

        def handle(result: dict | None) -> None:
            if not result:
                return
            self._log(f"▶ Feedback for {result['agent_id']}…")
            self.run_worker(
                lambda: self._improve_skill_worker(
                    result["agent_id"],
                    result["feedback"],
                    result["last_output"],
                ),
                thread=True,
                name="improve_skill",
            )

        self.push_screen(FeedbackScreen(agent_id, last_output), handle)

    def action_show_skills(self) -> None:
        self._log("── Skill Levels ──────────")
        for name in self._active_agents:
            skill = self._db.get_skill(name)
            lvl   = skill["skill_level"]
            bar   = "█" * int(lvl * 10) + "░" * (10 - int(lvl * 10))
            override = "✎" if skill.get("system_prompt_override") else " "
            emoji = AGENT_DEFS.get(name, ("?", "", ""))[0]
            self._log(f"  {emoji} {name:<13} {override} [{bar}] {lvl:.2f}")

    def action_history(self) -> None:
        self.push_screen(HistoryScreen(self._db))

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
            work_zone = "SERVER_ROOM" if target_agent == "Accountant" else sprite.home_zone
            sprite.move_to(work_zone)
            sprite.set_working()

        state = AgentState(agent_id=target_agent, task=task).model_dump()
        self.run_worker(
            lambda s=state: self._graph_worker(s),
            thread=True,
            name=f"task-{target_agent}",
        )

    # ── Worker functions (blocking → thread) ──────────────────────────────────

    def _graph_worker(self, state: dict[str, Any]) -> None:
        if self._graph is None:
            return
        agent_id = state.get("agent_id", "?")
        try:
            result = self._graph.invoke(state)
            self.call_from_thread(
                self.post_message,
                TaskCompleted(
                    agent_id=result.get("agent_id", agent_id),
                    result=result.get("last_result", ""),
                    cost=result.get("cost_usd", 0.0),
                    tokens=result.get("tokens_used", 0),
                    model=result.get("model_used", ""),
                ),
            )
        except BudgetExceededError as exc:
            self.call_from_thread(
                self.post_message,
                WorkerError(agent_id, str(exc), is_budget=True),
            )
        except Exception as exc:
            self.call_from_thread(
                self.post_message,
                WorkerError(agent_id, f"{type(exc).__name__}: {exc}"),
            )

    def _night_watch_worker(self) -> None:
        tasks = [
            ("Accountant",   "Generate nightly token-usage summary with today's totals."),
            ("Librarian",    "Review HR policy archive and flag items needing attention."),
            ("Orchestrator", "Prepare morning briefing: top 3 priorities for tomorrow."),
            ("CommsExpert",  "Draft one LinkedIn post idea about a current HR trend."),
        ]
        for agent_id, task_text in tasks:
            if not (agent_id in self._active_agents or agent_id in self._sprites):
                continue
            state = AgentState(agent_id=agent_id, task=task_text).model_dump()
            try:
                if self._graph:
                    result  = self._graph.invoke(state)
                    snippet = result.get("last_result", "")[:120]
                    task_id = self._db.add_scheduled_task(agent_id, "@nightly", task_text)
                    self._db.add_pending_result(task_id, agent_id, snippet)
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
            except BudgetExceededError as exc:
                self.call_from_thread(
                    self.post_message,
                    WorkerError(agent_id, str(exc), is_budget=True),
                )
                break   # stop remaining night-watch tasks if budget exhausted
            except Exception as exc:
                self.call_from_thread(
                    self.post_message,
                    WorkerError(agent_id, f"{type(exc).__name__}: {exc}"),
                )

    def _improve_skill_worker(
        self, agent_id: str, feedback: str, last_output: str
    ) -> None:
        try:
            instruction = improve_skill(
                agent_id, feedback, last_output, self._accountant, self._db
            )
            skill = self._db.get_skill(agent_id)
            self.call_from_thread(
                self.post_message,
                SkillImproved(agent_id, instruction, skill["skill_level"]),
            )
        except Exception as exc:
            self.call_from_thread(
                self.post_message,
                WorkerError(agent_id, f"improve_skill failed: {type(exc).__name__}: {exc}"),
            )

    # ── Message handlers ──────────────────────────────────────────────────────

    def on_task_completed(self, msg: TaskCompleted) -> None:
        self._total_tokens += msg.tokens
        self._total_cost   += msg.cost
        self._last_results[msg.agent_id] = msg.result

        snippet = (msg.result[:58] + "…") if len(msg.result) > 58 else msg.result
        self._log(f"[{msg.agent_id}] {snippet}")
        if msg.tokens:
            model_tag = msg.model.split("-")[1] if "-" in msg.model else msg.model
            self._log(f"  ↳ {msg.tokens} tok · ${msg.cost:.5f} · {model_tag}")

        self._update_stat("#token-counter", f"Tokens: {self._total_tokens:,}")
        self._update_stat("#cost-display",  f"Cost:   ${self._total_cost:.5f}")
        if msg.model:
            model_short = "Haiku" if "haiku" in msg.model.lower() else "Sonnet"
            self._update_stat("#model-display", f"Model:  {model_short}")

        self._show_speech_bubble(msg.agent_id, snippet)

        # Dynamic agent spawning if Recruiter mentioned new agents
        if msg.agent_id == "Recruiter":
            new_agents = self._parse_recruited_agents(msg.result)
            for agent_id in new_agents:
                self._spawn_agent(agent_id)

        # Return sprite to home zone + normal animation speed
        sprite = self._sprites.get(msg.agent_id)
        if sprite:
            sprite.move_to(sprite.home_zone)
            sprite.set_idle(False)

        self._update_budget_bar()
        self._update_roster()

    def on_cost_estimate(self, msg: CostEstimate) -> None:
        model_short = "Haiku" if "haiku" in msg.model.lower() else "Sonnet"
        self._update_stat(
            "#est-cost-display",
            f"Est:    ${msg.estimated_cost:.5f} ({model_short})",
        )
        self._update_stat("#model-display", f"Model:  {model_short}")

        # Speed up the active agent's animation while working
        sprite = self._sprites.get(msg.agent_id)
        if sprite:
            sprite.set_working()

    def on_skill_improved(self, msg: SkillImproved) -> None:
        self._log(f"[Skill ↑] {msg.agent_id} → {msg.new_level:.2f}")
        short = msg.instruction[:60] + ("…" if len(msg.instruction) > 60 else "")
        self._log(f"  Instruction: {short}")
        self._update_roster()

    def on_agent_spawned(self, msg: AgentSpawned) -> None:
        self._log(f"★ {msg.agent_id} joined the office!")

    def on_worker_error(self, msg: WorkerError) -> None:
        if msg.is_budget:
            self._log(f"[BUDGET ⛔] {msg.agent_id}: budget cap reached")
            self._show_banner("⛔ Budget cap reached — increase DAILY_BUDGET_USD", color="#FF4444")
            self._update_budget_bar()
        else:
            self._log(f"[ERROR ✗] {msg.agent_id}: {msg.error}")
        # Return sprite to idle so it doesn't stay in "working" state
        sprite = self._sprites.get(msg.agent_id)
        if sprite:
            sprite.move_to(sprite.home_zone)
            sprite.set_idle(False)

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
        _, color, _ = AGENT_DEFS.get(agent_id, ("", "#aaaacc", ""))
        agent_layer  = self.query_one("#agent-layer", Container)
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

    def _update_budget_bar(self) -> None:
        stats  = self._accountant.session_stats
        used   = stats["session_cost"]
        budget = self._accountant.daily_budget_usd
        pct    = stats["budget_pct"]
        filled = int(pct / 10)
        bar    = "█" * filled + "░" * (10 - filled)
        color  = "#FF4444" if pct > 80 else "#FF8C00" if pct > 50 else "#00FF88"
        self._update_stat(
            "#budget-display",
            f"Budget: ${budget - used:.4f} rem [{bar}]",
        )
        try:
            self.query_one("#budget-display", Static).styles.color = color
        except Exception:
            pass
        self._update_stat(
            "#budget-bar",
            f" Budget: ${used:.4f} / ${budget:.2f} used ({pct:.1f}%)",
        )

    def _update_roster(self) -> None:
        lines: list[str] = []
        for name in self._active_agents:
            skill = self._db.get_skill(name)
            lvl   = skill["skill_level"]
            bar   = "█" * int(lvl * 5) + "░" * (5 - int(lvl * 5))
            emoji = AGENT_DEFS.get(name, ("?", "", ""))[0]
            in_office = name in self._sprites
            presence = "" if in_office else "💤"
            lines.append(f"{emoji} {name[:11]:<11} [{bar}] {presence}")
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
            skill  = self._db.get_skill(name)
            self._log(f"◈ {name} @ {zone}  skill={skill['skill_level']:.2f}")

    # ── ChromaDB seed (deduplication by ID) ──────────────────────────────────

    def _seed_vector_memory(self) -> None:
        policies = [
            ("policy-001", "Remote work policy (HR-104): Employees may work remotely up to 3 days/week with manager approval. Core hours are 10:00–16:00 local time."),
            ("policy-002", "Equipment reimbursement (HR-201): Home office equipment up to €500/year is reimbursable with receipt and manager sign-off within 30 days of purchase."),
            ("policy-003", "Annual leave (HR-301): Employees are entitled to 26 days annual leave per year. Minimum 10 consecutive days must be taken in the calendar year."),
            ("policy-004", "Performance review (HR-401): Reviews are conducted bi-annually in June and December. Ratings: Exceeds / Meets / Below expectations. Ratings drive bonus calculations."),
            ("policy-005", "Parental leave (HR-501): Primary caregivers receive 26 weeks fully paid. Secondary caregivers receive 4 weeks. Applies from first day of employment."),
            ("policy-006", "Learning & Development (HR-601): Each employee has €1500/year L&D budget. Requires manager approval. Unused budget does not roll over."),
        ]
        for doc_id, text in policies:
            try:
                # ChromaDB deduplicates by ID; this is idempotent
                self._vector.add_document("hr_policies", doc_id, text)
            except Exception:
                pass


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    app = PixelHRApp()
    app.run()
