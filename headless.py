"""
Pixel HR Office — headless Night Watch runner.

Runs scheduled agent tasks without the TUI, stores results in SQLite
so they appear as notifications on next `python app.py` launch.

Usage:
    python headless.py             # run once and exit
    python headless.py --daemon    # loop every 60 s (cron-style)
    python headless.py --interval 300  # loop every 300 s
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from datetime import datetime, timezone

# Ensure project root is on path when called directly
sys.path.insert(0, os.path.dirname(__file__))

from db.memory import Database, VectorMemory
from engine.agents import AgentState, TokenAccountant
from engine.office_graph import build_graph

# ── Night Watch task schedule ──────────────────────────────────────────────────

NIGHT_TASKS = [
    ("Accountant",   "Generate a nightly token-usage summary. Include today's totals and top 3 cost drivers."),
    ("Librarian",    "Review and summarise any new HR policies. Flag anything that requires HR team attention."),
    ("Orchestrator", "Prepare a morning briefing: top 3 priorities for tomorrow based on task history."),
    ("CommsExpert",  "Draft one LinkedIn post idea based on current HR trends."),
]


def run_night_watch(db: Database, accountant: TokenAccountant, graph: object) -> int:
    """Execute all night-watch tasks. Returns number of results saved."""
    saved = 0
    print(f"\n[Night Watch] Starting — {datetime.now().isoformat()}")

    for agent_id, task_text in NIGHT_TASKS:
        print(f"  [{agent_id}] {task_text[:60]}…", end=" ", flush=True)
        state = AgentState(agent_id=agent_id, task=task_text).model_dump()
        try:
            result    = graph.invoke(state)  # type: ignore[union-attr]
            snippet   = result.get("last_result", "")[:120]
            tokens    = result.get("tokens_used", 0)
            cost      = result.get("cost_usd", 0.0)
            task_id   = db.add_scheduled_task(agent_id, "@nightly", task_text)
            db.add_pending_result(task_id, agent_id, snippet)
            db.log_task("night_watch", agent_id, tokens, cost)
            print(f"✓  ({tokens} tok, ${cost:.5f})")
            saved += 1
        except Exception as exc:
            print(f"✗  {exc}")

    print(f"[Night Watch] Done. {saved} results saved.")
    return saved


def main() -> None:
    parser = argparse.ArgumentParser(description="Pixel HR Office — Night Watch")
    parser.add_argument(
        "--daemon", action="store_true",
        help="Run repeatedly (--interval seconds between runs)",
    )
    parser.add_argument(
        "--interval", type=int, default=60,
        help="Seconds between runs in daemon mode (default: 60)",
    )
    args = parser.parse_args()

    db   = Database("pixel_hr.db")
    vect = VectorMemory("./chroma_db")
    accountant = TokenAccountant(
        db=db,
        api_key=os.environ.get("ANTHROPIC_API_KEY"),
    )

    db.connect()
    vect.connect()
    graph = build_graph(accountant, db, vect)

    mock_note = " [MOCK MODE — set ANTHROPIC_API_KEY for real calls]" if accountant._mock_mode else ""
    print(f"Pixel HR Office Night Watch{mock_note}")

    if args.daemon:
        print(f"Daemon mode: running every {args.interval}s. Ctrl-C to stop.")
        try:
            while True:
                run_night_watch(db, accountant, graph)
                print(f"  Sleeping {args.interval}s…")
                time.sleep(args.interval)
        except KeyboardInterrupt:
            print("\nDaemon stopped.")
    else:
        run_night_watch(db, accountant, graph)

    db.close()


if __name__ == "__main__":
    main()
