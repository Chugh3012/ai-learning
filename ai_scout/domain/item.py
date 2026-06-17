"""ScoredItem — a candidate item carried from selection to a sink."""
from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class ScoredItem(BaseModel):
    """One selected item: the shared KB row plus this profile's final score
    (relevance + affinity + interest bonus). Immutable value object passed selection -> sink."""
    model_config = ConfigDict(frozen=True)

    id: int
    title: str
    url: str
    summary: str
    source_id: int | None
    topic: str | None
    category: str | None
    score: float
