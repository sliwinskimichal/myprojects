"""
Pixel HR Office — headless Night Watch runner.

Runs scheduled agent tasks without the TUI, stores results in SQLite
so they appear as notifications on next `python app.py` launch.

Usage:
    python headless.py              # run once and exit
    python headless.py --daemon     # cron-style daemon (runs tasks at configured times)
    python headless.py --interval 300  # fallback: simple polling every 300 s
    python headless.py --list-tasks # show what would run

Cron schedule (default):
    08:00  Accountant  — nightly token-usage summary
    08:05  Librarian   — policy review + indexing
    08:10  Orchestrator — morning briefing
    08:15  CommsExpert — LinkedIn post idea

Override via env vars:
    NIGHT_WATCH_TIME=09:00        # single daily run time (all tasks)
    DAILY_BUDGET_USD=0.50         # override default budget cap
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from datetime import datetime, timezone
from typing import Any

sys.path.insert(0, os.path.dirname(__file__))

from db.memory import Database, VectorMemory
from engine.agents import AgentState, TokenAccountant
from engine.office_graph import build_graph

try:
    import schedule as _schedule
    _SCHEDULE_AVAILABLE = True
except ImportError:
    _SCHEDULE_AVAILABLE = False

# ── Scheduled tasks ────────────────────────────────────────────────────────────

NIGHT_TASKS: list[dict[str, Any]] = [
    {
        "agent_id":    "Accountant",
        "run_at":      "08:00",
        "task":        "Generate a nightly token-usage summary. Include today's totals, top cost drivers, and one optimisation tip.",
        "task_type":   "format",
    },
    {
        "agent_id":    "Librarian",
        "run_at":      "08:05",
        "task":        "Review available HR policies and flag anything that may need updating or HR team attention.",
        "task_type":   "research",
    },
    {
        "agent_id":    "Orchestrator",
        "run_at":      "08:10",
        "task":        "Prepare a morning briefing: top 3 action priorities for today based on recent task history.",
        "task_type":   "general",
    },
    {
        "agent_id":    "CommsExpert",
        "run_at":      "08:15",
        "task":        "Draft one LinkedIn post idea about a current HR trend. Include a hook, insight, and call to action.",
        "task_type":   "linkedin",
    },
]


# ── Core runner ────────────────────────────────────────────────────────────────

class NightWatchRunner:
    def __init__(self) -> None:
        self.db          = Database("pixel_hr.db")
        self.vector      = VectorMemory("./chroma_db")
        self.accountant  = TokenAccountant(
            db=self.db,
            api_key=os.environ.get("ANTHROPIC_API_KEY"),
            daily_budget_usd=float(os.environ.get("DAILY_BUDGET_USD", "1.0")),
        )
        self.graph: Any  = None

    def setup(self) -> None:
        self.db.connect()
        self.vector.connect()
        self.graph = build_graph(self.accountant, self.db, self.vector)

    def teardown(self) -> None:
        self.db.close()

    def run_task(self, task_def: dict[str, Any]) -> bool:
        agent_id  = task_def["agent_id"]
        task_text = task_def["task"]
        print(f"  [{agent_id}] {task_text[:65]}…", end=" ", flush=True)

        state = AgentState(agent_id=agent_id, task=task_text).model_dump()
        try:
            result   = self.graph.invoke(state)
            snippet  = result.get("last_result", "")[:120]
            tokens   = result.get("tokens_used", 0)
            cost     = result.get("cost_usd", 0.0)
            task_id  = self.db.add_scheduled_task(agent_id, task_def.get("run_at", "@once"), task_text)
            self.db.add_pending_result(task_id, agent_id, snippet)
            print(f"✓  ({tokens} tok, ${cost:.5f})")
            return True
        except RuntimeError as exc:
            if "budget" in str(exc).lower():
                print(f"✗ BUDGET CAP: {exc}")
            else:
                print(f"✗  {exc}")
            return False
        except Exception as exc:
            print(f"✗  {exc}")
            return False

    def run_all(self) -> int:
        print(f"\n[Night Watch] {datetime.now().isoformat()}")
        stats = self.accountant.session_stats
        print(f"  Budget: ${stats['session_cost']:.4f} / ${self.accountant.daily_budget_usd:.2f}"
              f"  ({stats['budget_pct']:.1f}%)")
        if stats["mock_mode"]:
            print("  ⚠ MOCK MODE — set ANTHROPIC_API_KEY for real API calls")

        saved = sum(1 for t in NIGHT_TASKS if self.run_task(t))
        print(f"[Night Watch] Done. {saved}/{len(NIGHT_TASKS)} tasks saved.")
        return saved


# ── Cron scheduling ────────────────────────────────────────────────────────────

def _setup_schedule(runner: NightWatchRunner, override_time: str | None) -> None:
    if not _SCHEDULE_AVAILABLE:
        print("  ⚠ 'schedule' library not installed — falling back to interval mode")
        return

    if override_time:
        # Run ALL tasks together at the single override time
        _schedule.every().day.at(override_time).do(runner.run_all)
        print(f"  Scheduled: all tasks at {override_time} daily")
    else:
        # Run each task at its individual time
        for t in NIGHT_TASKS:
            run_at = t.get("run_at", "08:00")
            _schedule.every().day.at(run_at).do(runner.run_task, task_def=t)
            print(f"  Scheduled: [{t['agent_id']}] at {run_at}")


def _daemon_loop_schedule(runner: NightWatchRunner, override_time: str | None) -> None:
    _setup_schedule(runner, override_time)
    print("Daemon started. Ctrl-C to stop.")
    try:
        while True:
            _schedule.run_pending()
            time.sleep(30)
    except KeyboardInterrupt:
        print("\nDaemon stopped.")


def _daemon_loop_interval(runner: NightWatchRunner, interval: int) -> None:
    print(f"Interval daemon: every {interval}s. Ctrl-C to stop.")
    try:
        while True:
            runner.run_all()
            print(f"  Sleeping {interval}s…")
            time.sleep(interval)
    except KeyboardInterrupt:
        print("\nDaemon stopped.")


# ── CLI ────────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="Pixel HR Office — Night Watch")
    parser.add_argument("--daemon",     action="store_true",  help="Run as cron-style daemon")
    parser.add_argument("--interval",   type=int, default=0,  help="Fallback: interval in seconds")
    parser.add_argument("--time",       type=str, default="", help="Override run time (HH:MM)")
    parser.add_argument("--list-tasks", action="store_true",  help="Show task schedule and exit")
    args = parser.parse_args()

    if args.list_tasks:
        print("Night Watch task schedule:")
        for t in NIGHT_TASKS:
            print(f"  {t.get('run_at', '?')}  [{t['agent_id']}]  {t['task'][:60]}…")
        return

    runner = NightWatchRunner()
    runner.setup()

    mock_note = " [MOCK MODE]" if runner.accountant._mock_mode else " [LIVE API]"
    print(f"Pixel HR Office Night Watch{mock_note}")

    try:
        if args.daemon:
            if _SCHEDULE_AVAILABLE and not args.interval:
                _daemon_loop_schedule(runner, args.time or os.environ.get("NIGHT_WATCH_TIME"))
            else:
                _daemon_loop_interval(runner, args.interval or 3600)
        else:
            runner.run_all()
    finally:
        runner.teardown()


if __name__ == "__main__":
    main()
