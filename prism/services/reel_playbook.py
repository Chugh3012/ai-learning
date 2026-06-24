from __future__ import annotations

import json

from pydantic import BaseModel

from prism.lib.config import CONFIG_DIR

class Playbook(BaseModel):
    """A reel 'theory': the swappable creative strategy for a reel — the script briefs (prompts),
    the b-roll queries for intro/outro, the call-to-action, and Style overrides. Lives in
    config/playbooks/<name>.json so experimenting with hooks/structure/pacing is config, not code.
    Empty prompt fields fall back to ReelScripter's built-in defaults."""

    name: str = "explainer"
    deep_system: str = ""
    roundup_system: str = ""
    intro_query: str = "artificial intelligence abstract technology"
    outro_query: str = "futuristic technology blue abstract"
    cta: str = "Follow for your daily AI signal."
    style: dict = {}

def load_playbook(name: str) -> Playbook:
    path = CONFIG_DIR / "playbooks" / f"{name}.json"
    if not path.exists():
        print(f"reel: playbook {name!r} not found; using built-in defaults")
        return Playbook(name=name)
    data = json.loads(path.read_text(encoding="utf-8"))
    data.pop("_comment", None)
    # Prompt briefs are authored as arrays of lines for editability; join them.
    for key in ("deep_system", "roundup_system"):
        if isinstance(data.get(key), list):
            data[key] = " ".join(str(line) for line in data[key])
    return Playbook(**data)
