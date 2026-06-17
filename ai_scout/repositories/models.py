"""SQLModel table models — the typed schema for the owned knowledge base.

These are the single source of truth for the KB schema (KnowledgeBase creates them via the engine)
and are directly reusable as FastAPI response models. The generic `signal(kind, value)` table holds
every per-lens signal (relevance, affinity:<lens>, sent:<lens>, fb_*:<lens>) — kinds are namespaced
strings, so new signal types need no migration.
"""
from __future__ import annotations

from sqlmodel import SQLModel, Field


class Source(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    title: str | None = None
    url: str | None = Field(default=None, unique=True)
    kind: str | None = None
    category: str | None = None


class Item(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    source_id: int | None = Field(default=None, foreign_key="source.id")
    title: str | None = None
    url: str | None = None
    summary: str | None = None
    published: int | None = Field(default=None, index=True)
    fetched_at: int | None = None
    hash: str | None = Field(default=None, unique=True)


class Tag(SQLModel, table=True):
    item_id: int = Field(foreign_key="item.id", primary_key=True)
    topic: str = Field(primary_key=True)


class Signal(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    item_id: int | None = Field(default=None, foreign_key="item.id")
    kind: str | None = None
    value: float | None = None
    ts: int | None = None


class Draft(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    item_id: int | None = Field(default=None, foreign_key="item.id", unique=True)
    status: str | None = None
    body: str | None = None
    created_at: int | None = None


class Embedding(SQLModel, table=True):
    item_id: int | None = Field(default=None, foreign_key="item.id", primary_key=True)
    vec: bytes | None = None
    ts: int | None = None
