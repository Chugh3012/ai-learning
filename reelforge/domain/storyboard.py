from __future__ import annotations

from pydantic import BaseModel

from reelforge.domain.style import Style

class Scene(BaseModel):
    """One beat of the reel: a line that is captioned (and later voiced), over a background.
    `query` is the short b-roll search phrase (stock providers); `visual_prompt` is the rich
    cinematic prompt for an AI video provider; `image` is reserved for a provided asset."""

    text: str = ""
    seconds: float = 3.0
    kicker: str = ""        # small top label, e.g. "01 / 05" or "AI RADAR"
    query: str = ""         # short b-roll keywords (stock search); empty falls back to `text`
    visual_prompt: str = "" # rich cinematic prompt for an AI video provider; empty falls back to query
    image: str = ""         # explicit b-roll asset (reserved); empty = provider or gradient

class Storyboard(BaseModel):
    """The full spec a video is built from — the data contract between content and rendering.
    Growth = new Storyboard (data), new Style preset (theme), or new provider (code), not a new
    render path."""

    scenes: list[Scene] = []
    style: Style = Style()
    music: str = ""         # optional path to a music bed
