from __future__ import annotations

OFFICE_MAP = """\
╔══════════════════════════════════════════════════════════════╗
║  ✦  PIXEL HR OFFICE  ✦                          v0.4 MVP    ║
╠══════════════════════════════════════════════════════════════╣
║                                                              ║
║   ┌────────────┐     ┌────────────┐     ┌────────────┐      ║
║   │  HRBP DESK │     │   VAULT    │     │  ARCHIVE   │      ║
║   │            │     │            │     │            │      ║
║   │  . . . .   │     │  . . . .   │     │  . . . .   │      ║
║   └────────────┘     └────────────┘     └────────────┘      ║
║                                                              ║
║   ┌────────────┐     ┌────────────┐     ┌────────────┐      ║
║   │  HR HALL   │     │SERVER ROOM │     │ IDLE ZONE  │      ║
║   │            │     │            │     │            │      ║
║   │  . . . .   │     │  . . . .   │     │  . . . .   │      ║
║   └────────────┘     └────────────┘     └────────────┘      ║
║                                                              ║
╚══════════════════════════════════════════════════════════════╝"""

# Zone coordinates (col, row) — character offsets within the map widget.
ZONES: dict[str, tuple[int, int]] = {
    "HRBP_DESK":   (5,  6),
    "VAULT":       (22, 6),
    "ARCHIVE":     (39, 6),
    "HR_HALL":     (5,  12),
    "SERVER_ROOM": (22, 12),
    "IDLE_ZONE":   (39, 12),
}

# Human-readable zone labels
ZONE_LABELS: dict[str, str] = {
    "HRBP_DESK":   "HRBP Desk",
    "VAULT":       "Vault",
    "ARCHIVE":     "Archive",
    "HR_HALL":     "HR Hall",
    "SERVER_ROOM": "Server Room",
    "IDLE_ZONE":   "Idle Zone",
}

# Zone header text (as it appears in OFFICE_MAP) → Rich accent color when occupied
_ZONE_HEADERS: dict[str, tuple[str, str]] = {
    "HRBP_DESK":   ("HRBP DESK",   "#00FF88"),
    "VAULT":       ("VAULT",       "#FFD700"),
    "ARCHIVE":     ("ARCHIVE",     "#00BFFF"),
    "HR_HALL":     ("HR HALL",     "#FF69B4"),
    "SERVER_ROOM": ("SERVER ROOM", "#FF8C00"),
    "IDLE_ZONE":   ("IDLE ZONE",   "#888888"),
}


def make_live_map(zone_agents: dict[str, list[str]]) -> str:
    """Return OFFICE_MAP with occupied zone headers highlighted via Rich markup."""
    text = OFFICE_MAP
    for zone, (header, color) in _ZONE_HEADERS.items():
        if zone_agents.get(zone):
            text = text.replace(
                header,
                f"[bold {color}]{header}[/bold {color}]",
            )
    return text
