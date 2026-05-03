OFFICE_MAP = """\
╔══════════════════════════════════════════════════════════════╗
║  ✦  PIXEL HR OFFICE  ✦                          v0.1 MVP    ║
╠══════════════════════════════════════════════════════════════╣
║                                                              ║
║   ┌────────────┐     ┌────────────┐     ┌────────────┐      ║
║   │  HRBP DESK │     │   VAULT    │     │  ARCHIVE   │      ║
║   │            │     │            │     │            │      ║
║   │  [🤖 zone] │     │ [💰 zone]  │     │ [📚 zone]  │      ║
║   └────────────┘     └────────────┘     └────────────┘      ║
║                                                              ║
║   ┌────────────┐     ┌────────────┐     ┌────────────┐      ║
║   │  HR HALL   │     │SERVER ROOM │     │ IDLE ZONE  │      ║
║   │            │     │            │     │            │      ║
║   │  [👥 zone] │     │ [⚡ zone]  │     │  [💤 zone] │      ║
║   └────────────┘     └────────────┘     └────────────┘      ║
║                                                              ║
╚══════════════════════════════════════════════════════════════╝\
"""

# Zone coordinates (col, row) — character offsets within the map widget.
# These align with the center of each room box above.
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
