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
    visual_system: str = ""   # brief for the AI-visuals prompt layer (VisualPromptWriter)
    intro_query: str = "artificial intelligence abstract technology"
    outro_query: str = "futuristic technology blue abstract"
    cta: str = "Follow for your daily AI signal."
    deep_beats: int = 5
    style: dict = {}

    def deep_scenes(self, title: str, body: str, scripter) -> list:
        # The playbook OWNS how its theory becomes scenes. Hook-first: scene 1 IS the spoken hook
        # (beat 1) — no title card, no numbering — so a scroll-stopping line lands immediately.
        from reelforge.domain.storyboard import Scene
        _hook, beats = scripter.script_deep(title, body, self.deep_system)
        if not beats:
            beats = [(title, self.intro_query)]
        beats = beats[: self.deep_beats]                 # keep it tight (~30s)
        scenes = [Scene(text=t, query=q or "technology abstract") for t, q in beats]
        scenes.append(Scene(text=self.cta, query=self.outro_query))
        return scenes

    def roundup_scenes(self, rows: list, scripter) -> list:
        from reelforge.domain.storyboard import Scene
        hook, script = scripter.script([(r.id, r.title, r.summary) for r in rows], self.roundup_system)
        scenes = [Scene(text=hook or "Today in AI", query=self.intro_query)]
        for r in rows:
            _h, line, query = (script.get(r.id, ("", "", "")) + ("", "", ""))[:3]
            scenes.append(Scene(text=line or r.title, query=query or "technology abstract"))
        scenes.append(Scene(text=self.cta, query=self.outro_query))
        return scenes

def load_playbook(name: str) -> Playbook:
    path = CONFIG_DIR / "playbooks" / f"{name}.json"
    if not path.exists():
        print(f"reel: playbook {name!r} not found; using built-in defaults")
        return Playbook(name=name)
    data = json.loads(path.read_text(encoding="utf-8"))
    data.pop("_comment", None)
    # Prompt briefs are authored as arrays of lines for editability; join them.
    for key in ("deep_system", "roundup_system", "visual_system"):
        if isinstance(data.get(key), list):
            data[key] = " ".join(str(line) for line in data[key])
    return Playbook(**data)
