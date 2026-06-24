from __future__ import annotations

from pydantic import BaseModel

from reelforge.domain.style import Style

class Scene(BaseModel):
    """One beat of the reel: a line that is captioned (and later voiced), over a background.
    `image` (b-roll path/URL) is optional — empty falls back to the branded gradient."""

    text: str = ""
    seconds: float = 3.0
    kicker: str = ""        # small top label, e.g. "01 / 05" or "AI RADAR"
    image: str = ""         # b-roll asset (added in a later checkpoint); empty = gradient

class Storyboard(BaseModel):
    """The full spec a video is built from — the data contract between content and rendering.
    Growth = new Storyboard (data), new Style preset (theme), or new provider (code), not a new
    render path."""

    scenes: list[Scene] = []
    style: Style = Style()
    music: str = ""         # optional path to a music bed
