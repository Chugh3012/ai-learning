"""ContentProducer — turns already-SELECTED items into HUMAN-REVIEW content drafts (a FORMAT).

The output shape is a named FORMAT in config/content.yml (e.g. 'reel', 'social'): the model returns
JSON and the review file renders whatever keys it produces. Selection (which items) happened
upstream in the Orchestrator + Selector; this only PRODUCES. Depends on a KnowledgeBase (DI).
"""
from __future__ import annotations

import json
import time

from ai_scout.lib import foundry
from ai_scout.lib.config import CONFIG_DIR, DRAFTS_DIR
from ai_scout.repositories.knowledge import KnowledgeBase

_CONTENT = CONFIG_DIR / "content.yml"


def load_format(name: str) -> dict:
    """Load a content FORMAT (production recipe) from config/content.yml. Each format carries a
    `temperature` and an `instruction` (the model prompt)."""
    import yaml
    formats = (yaml.safe_load(_CONTENT.read_text(encoding="utf-8")) or {}).get("formats", {})
    if name not in formats:
        raise KeyError(f"content format '{name}' not found in {_CONTENT.name}")
    fmt = dict(formats[name])
    fmt.setdefault("temperature", 0.6)
    fmt.setdefault("instruction", "")
    return fmt


class ContentProducer:
    def __init__(self, kb: KnowledgeBase, endpoint: str, model: str):
        self.kb = kb
        self.endpoint = endpoint
        self.model = model

    def produce(self, profile, items: list) -> int:
        """Produce a content kit per selected item using the profile's content FORMAT. The
        Orchestrator owns sent:<lens> marking. Returns count produced (0 = nothing/unconfigured)."""
        if not self.endpoint or not items:
            return 0
        fmt_name = getattr(profile, "format", None)
        if not fmt_name:
            print("draft: profile has no `format` — nothing to produce")
            return 0
        try:
            fmt = load_format(fmt_name)
        except (FileNotFoundError, KeyError) as e:
            print(f"draft: skipped ({e})")
            return 0
        try:
            client = foundry.openai_client(self.endpoint)
        except Exception as e:  # noqa: BLE001 — optional stage, never break the pipeline
            print(f"draft: skipped (client init failed: {e})")
            return 0

        now = int(time.time())
        made = 0
        for it in items:
            try:
                resp = client.chat.completions.create(
                    model=self.model,
                    messages=[
                        {"role": "system", "content": fmt["instruction"]},
                        {"role": "user",
                         "content": f"Title: {it.title}\n\nSummary: {(it.summary or '')[:1200]}"},
                    ],
                    temperature=fmt["temperature"],
                    response_format={"type": "json_object"},
                    max_tokens=600,
                )
                body = json.loads(resp.choices[0].message.content)
            except Exception as e:  # noqa: BLE001
                print(f"draft: stopped ({e})")
                break
            body["_format"] = fmt_name
            self.kb.add_draft(it.id, json.dumps(body), now)
            made += 1
        self.kb.commit()
        print(f"draft: produced {made} pending kit(s) (format '{fmt_name}')")
        return made


def write_review(kb: KnowledgeBase):
    """Write pending content drafts to a human-review markdown file. Generic over the JSON shape:
    prints whatever keys each format produced. Returns the path, or None when there are no drafts."""
    from datetime import datetime, timezone
    rows = kb.pending_drafts()
    if not rows:
        return None
    DRAFTS_DIR.mkdir(exist_ok=True)
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    out = DRAFTS_DIR / f"{today}-review.md"
    lines = [f"# Content drafts for review — {today}", "",
             f"_{len(rows)} pending. Edit/approve before any publishing (publishing is manual)._", ""]
    for draft_id, title, url, body_json in rows:
        body = json.loads(body_json)
        fmt = body.pop("_format", "")
        lines.append(f"## #{draft_id} — {title}")
        lines.append(f"_source: {url}{(' · format: ' + fmt) if fmt else ''}_")
        lines.append("")
        for key, val in body.items():
            if isinstance(val, list):
                lines.append(f"**{key}:**")
                for i, v in enumerate(val, 1):
                    if isinstance(v, dict):
                        parts = " · ".join(f"{k}: {vv}" for k, vv in v.items())
                        lines.append(f"{i}. {parts}")
                    else:
                        lines.append(f"- {v}")
            else:
                lines.append(f"**{key}:** {val}")
            lines.append("")
        lines.append("---")
        lines.append("")
    out.write_text("\n".join(lines), encoding="utf-8")
    return out
