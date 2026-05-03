from __future__ import annotations

from textual.geometry import Offset
from textual.reactive import reactive
from textual.widgets import Static

from ui.office_map import ZONES, ZONE_LABELS

# ── Agent definitions ─────────────────────────────────────────────────────────
# (emoji, accent_color_hex, home_zone)
AGENT_DEFS: dict[str, tuple[str, str, str]] = {
    "Orchestrator": ("🤖", "#00FF88", "HRBP_DESK"),
    "Accountant":   ("💰", "#FFD700", "VAULT"),
    "Librarian":    ("📚", "#00BFFF", "ARCHIVE"),
    "Recruiter":    ("👥", "#FF69B4", "HR_HALL"),
    "CommsExpert":  ("🔗", "#FF8C00", "HR_HALL"),
    "Tester":       ("🐞", "#9B59B6", "SERVER_ROOM"),
    "QA_Critic":    ("🔬", "#E74C3C", "ARCHIVE"),
    "Analyst":      ("📊", "#2ECC71", "ARCHIVE"),
}

# ── Pixel-art animation frames ────────────────────────────────────────────────
# 3 rows × 6 chars. "E" is replaced by the agent's emoji at render time.
_FRAMES: list[tuple[str, str, str]] = [
    ("▄▄█▄▄", "█ E █", "▀▀▀▀▀"),
    ("▄█▄█▄", "█ E █", "▀▄▀▄▀"),
    ("▄▄█▄▄", "█ E █", "▀▀▀▀▀"),
]

# Idle frame (dimmed, static)
_IDLE_FRAME = ("░░█░░", "░ E ░", "░░░░░")


class AgentSprite(Static):
    """A pixel-art sprite widget representing one HR office agent."""

    DEFAULT_CSS = """
    AgentSprite {
        width: 7;
        height: 3;
        position: absolute;
        background: transparent;
        border: none;
        padding: 0;
    }
    """

    _frame_index: reactive[int] = reactive(0)

    def __init__(
        self,
        name: str,
        emoji: str,
        color: str,
        home_zone: str,
        *,
        widget_id: str | None = None,
    ) -> None:
        super().__init__(id=widget_id or f"sprite-{name.lower().replace('_', '-')}")
        self.agent_name  = name
        self.emoji       = emoji
        self.color       = color
        self.home_zone   = home_zone
        self.current_zone = home_zone
        self._is_idle    = False
        self._timer      = None

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    # Normal and working frame intervals (seconds)
    _INTERVAL_IDLE    = 0.55
    _INTERVAL_WORKING = 0.15

    def on_mount(self) -> None:
        self._timer = self.set_interval(self._INTERVAL_IDLE, self._next_frame)
        x, y = ZONES.get(self.home_zone, (4, 4))
        self.styles.offset = Offset(x, y)

    # ── Rendering ─────────────────────────────────────────────────────────────

    def _render_sprite(self) -> str:
        if self._is_idle:
            top, mid, bot = _IDLE_FRAME
        else:
            top, mid, bot = _FRAMES[self._frame_index]
        mid = mid.replace("E", self.emoji)
        c = self.color
        dim = "[dim]" if self._is_idle else ""
        end_dim = "[/dim]" if self._is_idle else ""
        lines = [
            f"{dim}[bold {c}]{top}[/]{end_dim}",
            f"{dim}[bold {c}]{mid}[/]{end_dim}",
            f"{dim}[bold {c}]{bot}[/]{end_dim}",
        ]
        return "\n".join(lines)

    def render(self) -> str:  # type: ignore[override]
        return self._render_sprite()

    # ── Animation helpers ─────────────────────────────────────────────────────

    def _next_frame(self) -> None:
        if not self._is_idle:
            self._frame_index = (self._frame_index + 1) % len(_FRAMES)
            self.update(self._render_sprite())

    # ── Public API ────────────────────────────────────────────────────────────

    # Maximum safe offsets to keep sprites visible inside the map container.
    # These are generous bounds; actual map is ~64 cols × 18 rows.
    _MAX_X = 60
    _MAX_Y = 16

    def move_to(self, zone: str) -> None:
        if zone not in ZONES:
            return
        x, y = ZONES[zone]
        # Guard: clamp to visible area so sprites never escape the container
        x = max(0, min(x, self._MAX_X))
        y = max(0, min(y, self._MAX_Y))
        self.current_zone = zone
        self.styles.animate(
            "offset",
            value=Offset(x, y),
            duration=1.5,
            easing="in_out_quart",
        )

    def set_idle(self, idle: bool) -> None:
        self._is_idle = idle
        target_opacity = 0.35 if idle else 1.0
        self.styles.animate("opacity", value=target_opacity, duration=0.5)
        # Slow animation when idle
        if self._timer:
            self._timer.stop()
        self._timer = self.set_interval(
            self._INTERVAL_IDLE if idle else self._INTERVAL_WORKING,
            self._next_frame,
        )
        self.update(self._render_sprite())

    def set_working(self) -> None:
        self._is_idle = False
        self.styles.animate("opacity", value=1.0, duration=0.2)
        # Speed up animation to show activity
        if self._timer:
            self._timer.stop()
        self._timer = self.set_interval(self._INTERVAL_WORKING, self._next_frame)
        self.update(self._render_sprite())

    @property
    def zone_label(self) -> str:
        return ZONE_LABELS.get(self.current_zone, self.current_zone)

    @property
    def current_offset(self) -> Offset:
        return self.styles.offset or Offset(0, 0)


# ── Factory ───────────────────────────────────────────────────────────────────

def create_sprites_for(names: list[str]) -> list[AgentSprite]:
    sprites = []
    for name in names:
        if name in AGENT_DEFS:
            emoji, color, home_zone = AGENT_DEFS[name]
            sprites.append(AgentSprite(name, emoji, color, home_zone))
    return sprites


def create_all_sprites() -> list[AgentSprite]:
    return create_sprites_for(list(AGENT_DEFS.keys()))
