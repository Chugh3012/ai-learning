from __future__ import annotations

from pydantic import BaseModel, ConfigDict

class ScoredItem(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: int
    title: str = ""
    url: str = ""
    summary: str = ""
    source_id: int | None = None
    topic: str | None = None
    category: str | None = None
    score: float = 0.0
