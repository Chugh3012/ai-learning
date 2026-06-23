from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from prism.lib.config import TOPICS_DIR

DEFAULT_TOPIC = "ai"

@dataclass(frozen=True)
class TopicPack:
    id: str
    dir: Path
    name: str
    brand: str
    tagline: str
    rubric: str
    tags: dict
    sources_opml: Path
    golden: Path
    thresholds: dict
    settings: dict


def _read_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}

def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return ""

def load_pack(topic_id: str) -> TopicPack:
    d = TOPICS_DIR / topic_id
    meta = _read_json(d / "pack.json")
    return TopicPack(
        id=topic_id,
        dir=d,
        name=str(meta.get("name", topic_id)),
        brand=str(meta.get("brand", "")),
        tagline=str(meta.get("tagline", "")),
        rubric=_read_text(d / "rubric.txt"),
        tags=_read_json(d / "tags.json").get("topics", {}),
        sources_opml=d / "sources.opml",
        golden=d / "eval" / "golden.jsonl",
        thresholds=_read_json(d / "eval.json"),
        settings=meta.get("settings", {}) if isinstance(meta.get("settings"), dict) else {},
    )

def list_topics() -> list[str]:
    if not TOPICS_DIR.exists():
        return []
    return sorted(p.name for p in TOPICS_DIR.iterdir()
                  if p.is_dir() and (p / "pack.json").exists())
