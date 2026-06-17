"""Brief — the learning-brief value objects produced by BriefBuilder and consumed by delivery sinks."""
from __future__ import annotations

from pydantic import BaseModel


class Card(BaseModel):
    """One item's teaching card in the learning brief."""
    lesson: str = ""
    try_it: str = ""


class Brief(BaseModel):
    """A rendered-ready learning brief: a one-line throughline (`theme`) over the day's picks, a
    teaching `card` per item id, and `connections` linking each pick to a past one this profile
    was already sent. All fields degrade gracefully to empty (titles-only fallback)."""
    theme: str = ""
    cards: dict[int, Card] = {}
    connections: dict[int, tuple[str, str]] = {}
