from __future__ import annotations

from textual.app import ComposeResult
from textual.geometry import Offset
from textual.reactive import reactive
from textual.widgets import Static

from ui.office_map import ZONES, ZONE_LABELS

# ── Agent definitions ─────────────────────────────────────────────────────────
# (name) → (emoji, accent_color_hex, home_zone)
AGENT_DEFS: dict[str, tuple[str, str, str]] = {
    "Orchestrator": ("🤖", "#00FF88", "HRBP_DESK"),
    "Accountant":   ("💰", "#FFD700", "VAULT"),
    "Librarian":    ("📚", "#00BFFF", "ARCHIVE"),
    "Recruiter":    ("👥", "#FF69B4", "HR_HALL"),
}

# ── Pixel art frames (5 chars wide, 3 rows each) ──────────────────────────────
# Each tuple: (top_row, middle_row, bottom_row)
# The middle row uses a placeholder "E" that gets replaced with the real emoji.
_FRAMES: list[tuple[str, str, str]] = [
    ("▄▄█▄▄", "█ E █", "▀▀▀▀▀"),
    ("▄█▄█▄", "█ E █", "▀▄▀▄▀"),
    ("▄▄█▄▄", "█ E █", "▀▀▀▀▀"),
]


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

    # Reactive attribute drives re-render on frame change
    _frame_index: reactive[int] = reactive(0)
    _status: reactive[str] = reactive("idle")

    def __init__(
        self,
        name: str,
        emoji: str,
        color: str,
        home_zone: str,
        *,
        widget_id: str | None = None,
    ) -> None:
        super().__init__(id=widget_id or f"sprite-{name.lower()}")
        self.agent_name = name
        self.emoji = emoji
        self.color = color
        self.home_zone = home_zone
        self.current_zone = home_zone

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    def on_mount(self) -> None:
        self.set_interval(0.45, self._next_frame)
        x, y = ZONES[self.home_zone]
        self.styles.offset = Offset(x, y)

    # ── Rendering ─────────────────────────────────────────────────────────────

    def _render_sprite(self) -> str:
        top, mid, bot = _FRAMES[self._frame_index]
        mid = mid.replace("E", self.emoji)
        c = self.color
        lines = [
            f"[bold {c}]{top}[/]",
            f"[bold {c}]{mid}[/]",
            f"[bold {c}]{bot}[/]",
        ]
        return "\n".join(lines)

    def render(self) -> str:  # type: ignore[override]
        return self._render_sprite()

    # ── Animation helpers ─────────────────────────────────────────────────────

    def _next_frame(self) -> None:
        self._frame_index = (self._frame_index + 1) % len(_FRAMES)
        self.update(self._render_sprite())

    def watch__frame_index(self, _value: int) -> None:
        self.update(self._render_sprite())

    # ── Public API ────────────────────────────────────────────────────────────

    def move_to(self, zone: str) -> None:
        """Animate the sprite to the given zone."""
        if zone not in ZONES:
            raise ValueError(f"Unknown zone: {zone!r}")
        x, y = ZONES[zone]
        self.current_zone = zone
        self._status = "moving"
        self.styles.animate(
            "offset",
            value=Offset(x, y),
            duration=1.5,
            easing="in_out_quart",
            on_complete=self._on_move_done,
        )

    def _on_move_done(self) -> None:
        self._status = "idle"

    def set_idle(self, idle: bool) -> None:
        """Fade sprite to indicate idle state."""
        target_opacity = 0.3 if idle else 1.0
        self.styles.animate("opacity", value=target_opacity, duration=0.5)
        self._status = "idle" if idle else "working"

    def set_working(self) -> None:
        self.set_idle(False)
        self._status = "working"

    @property
    def zone_label(self) -> str:
        return ZONE_LABELS.get(self.current_zone, self.current_zone)


# ── Factory ───────────────────────────────────────────────────────────────────

def create_all_sprites() -> list[AgentSprite]:
    """Instantiate one AgentSprite per entry in AGENT_DEFS."""
    sprites: list[AgentSprite] = []
    for name, (emoji, color, home_zone) in AGENT_DEFS.items():
        sprites.append(AgentSprite(name, emoji, color, home_zone))
    return sprites
