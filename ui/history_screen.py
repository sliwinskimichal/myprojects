"""
Task history modal screen — shows recent SQLite task_history rows.
Supports export to .txt, .json, and .csv formats.
"""

from __future__ import annotations

import csv
import io
import json
import os
from datetime import datetime
from typing import TYPE_CHECKING

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, DataTable, Label, Static

if TYPE_CHECKING:
    from db.memory import Database


class HistoryScreen(ModalScreen[None]):
    """Modal showing the last 50 task history records from SQLite."""

    CSS = """
    HistoryScreen > Vertical {
        width: 88;
        height: 32;
        background: #0f0f1a;
        border: solid #00FF88;
        padding: 1 2;
        margin: 2 auto;
    }
    .history-title {
        color: #00FF88;
        text-style: bold;
        margin-bottom: 1;
    }
    DataTable {
        height: 1fr;
        background: #070710;
        border: solid #1a1a3a;
    }
    .btn-row {
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
    Button.secondary {
        background: #002233;
        color: #00BFFF;
        border: solid #00BFFF;
    }
    Button.cancel {
        background: #1a1a2e;
        color: #aaaacc;
        border: solid #333355;
    }
    #export-status {
        color: #FFD700;
        height: 1;
    }
    """

    BINDINGS = [
        Binding("escape", "dismiss_modal", "Close", show=False),
    ]

    def __init__(self, db: "Database") -> None:
        super().__init__()
        self._db = db

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Static("◈ TASK HISTORY", classes="history-title")
            table = DataTable()
            table.add_columns("Agent", "Type", "Tokens", "Cost $", "Model", "Time")
            yield table
            yield Static("", id="export-status")
            with Horizontal(classes="btn-row"):
                yield Button("Export TXT",  id="btn-export",      classes="primary")
                yield Button("Export JSON", id="btn-export-json", classes="secondary")
                yield Button("Export CSV",  id="btn-export-csv",  classes="secondary")
                yield Button("Close",       id="btn-close",       classes="cancel")

    def on_mount(self) -> None:
        table = self.query_one(DataTable)
        rows  = self._db.get_task_history(limit=50)
        for row in rows:
            ts = row.get("timestamp", "")
            try:
                ts = datetime.fromisoformat(ts).strftime("%H:%M:%S")
            except Exception:
                pass
            table.add_row(
                row.get("agent_id",    "?"),
                row.get("task_type",   "?"),
                str(row.get("tokens_used", 0)),
                f"{row.get('cost_usd', 0):.5f}",
                (row.get("model_used", "") or "")[:12],
                ts,
            )

    def on_button_pressed(self, event: Button.Pressed) -> None:
        bid = event.button.id
        if bid == "btn-export":
            self._export_txt()
        elif bid == "btn-export-json":
            self._export_json()
        elif bid == "btn-export-csv":
            self._export_csv()
        else:
            self.dismiss()

    def action_dismiss_modal(self) -> None:
        self.dismiss()

    # ── Export helpers ────────────────────────────────────────────────────────

    def _rows(self, limit: int = 200) -> list[dict]:
        return self._db.get_task_history(limit=limit)

    def _set_status(self, msg: str) -> None:
        try:
            self.query_one("#export-status", Static).update(msg)
        except Exception:
            pass

    def _export_txt(self) -> None:
        rows     = self._rows()
        filename = f"task_history_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
        path     = os.path.join(os.getcwd(), filename)
        lines    = ["Pixel HR Office — Task History Export", "=" * 60, ""]
        for row in rows:
            lines.append(
                f"[{row.get('timestamp', '')}] {row.get('agent_id', '?')} | "
                f"{row.get('task_type', '?')} | "
                f"{row.get('tokens_used', 0)} tok | "
                f"${row.get('cost_usd', 0):.5f} | "
                f"{row.get('model_used', '')}"
            )
        lines += ["", f"Total rows: {len(rows)}"]
        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write("\n".join(lines))
            self._set_status(f"Saved → {filename}")
        except Exception as exc:
            self._set_status(f"Export failed: {exc}")

    def _export_json(self) -> None:
        rows     = self._rows()
        filename = f"task_history_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        path     = os.path.join(os.getcwd(), filename)
        payload  = [
            {
                "agent_id":   row.get("agent_id", ""),
                "task_type":  row.get("task_type", ""),
                "tokens_used": row.get("tokens_used", 0),
                "cost_usd":   row.get("cost_usd", 0.0),
                "model_used": row.get("model_used", ""),
                "timestamp":  row.get("timestamp", ""),
            }
            for row in rows
        ]
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(payload, f, indent=2, ensure_ascii=False)
            self._set_status(f"Saved → {filename}  ({len(rows)} records)")
        except Exception as exc:
            self._set_status(f"JSON export failed: {exc}")

    def _export_csv(self) -> None:
        rows     = self._rows()
        filename = f"task_history_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
        path     = os.path.join(os.getcwd(), filename)
        headers  = ["agent_id", "task_type", "tokens_used", "cost_usd", "model_used", "timestamp"]
        try:
            with open(path, "w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=headers, extrasaction="ignore")
                writer.writeheader()
                writer.writerows(rows)
            self._set_status(f"Saved → {filename}  ({len(rows)} rows)")
        except Exception as exc:
            self._set_status(f"CSV export failed: {exc}")
