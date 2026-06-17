from __future__ import annotations

from pydantic import BaseModel

class Card(BaseModel):
    lesson: str = ""
    try_it: str = ""

class Brief(BaseModel):
    theme: str = ""
    cards: dict[int, Card] = {}
    connections: dict[int, tuple[str, str]] = {}
