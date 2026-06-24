from __future__ import annotations

from pydantic import BaseModel

from reelforge.domain.style import Style

class Scene(BaseModel):
    """One beat of the reel: a line that is captioned (and later voiced), over a background.
    `query` is the b-roll search phrase (falls back to the text); `image` is reserved for a
    provided asset."""

    text: str = ""
    seconds: float = 3.0
    kicker: str = ""        # small top label, e.g. "01 / 05" or "AI RADAR"
    query: str = ""         # b-roll search terms; empty falls back to `text`
    image: str = ""         # explicit b-roll asset (reserved); empty = provider or gradient

class Storyboard(BaseModel):
    """The full spec a video is built from — the data contract between content and rendering.
    Growth = new Storyboard (data), new Style preset (theme), or new provider (code), not a new
    render path."""

    scenes: list[Scene] = []
    style: Style = Style()
    music: str = ""         # optional path to a music bed
