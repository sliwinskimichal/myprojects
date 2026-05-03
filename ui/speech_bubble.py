"""
SpeechBubble widget — a transient popup that appears next to an agent sprite
and auto-dismisses after a configurable duration.
"""

from __future__ import annotations

from textual.geometry import Offset
from textual.widgets import Static


class SpeechBubble(Static):
    """
    A small speech-bubble popup rendered near a sprite.

    Positioning: the bubble is placed at (sprite_x + 8, sprite_y - 1) so it
    appears to the right of the 7-char-wide sprite. If the x position would
    overflow the right edge it shifts left automatically via CSS max-width.
    """

    DEFAULT_CSS = """
    SpeechBubble {
        position: absolute;
        width: 24;
        height: auto;
        background: #1a1a2e;
        border: solid #00FF88;
        padding: 0 1;
        color: #e0e0e0;
        text-style: italic;
        layer: above;
        opacity: 0.0;
    }
    """

    def __init__(
        self,
        text: str,
        agent_color: str,
        sprite_offset: Offset,
        *,
        duration: float = 4.0,
        bubble_id: str | None = None,
    ) -> None:
        # Truncate long text so the bubble stays small
        display_text = text[:80] + ("…" if len(text) > 80 else "")
        super().__init__(display_text, id=bubble_id)
        self._agent_color = agent_color
        self._sprite_offset = sprite_offset
        self._duration = duration

    # Bubble is 24 chars wide; keep it inside a ~64-col container
    _MAX_BUBBLE_X = 38   # 64 - 24 - 2 margin
    _MAX_BUBBLE_Y = 15

    def on_mount(self) -> None:
        # Position to the right of the sprite; clamp so it stays on-screen
        x = self._sprite_offset.x + 8
        y = self._sprite_offset.y - 1
        x = max(0, min(x, self._MAX_BUBBLE_X))
        y = max(0, min(y, self._MAX_BUBBLE_Y))
        self.styles.offset = Offset(x, y)
        self.styles.border = ("solid", self._agent_color)

        # Fade in
        self.styles.animate("opacity", value=1.0, duration=0.3)
        # Schedule auto-dismiss
        self.set_timer(self._duration, self._dismiss)

    def _dismiss(self) -> None:
        self.styles.animate(
            "opacity",
            value=0.0,
            duration=0.5,
            on_complete=self.remove,
        )
