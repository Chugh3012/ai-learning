from __future__ import annotations

import json
from pathlib import Path

from jinja2 import Environment, FileSystemLoader

from prism.domain.brief import Brief, Card
from prism.lib import foundry
from prism.lib.text import clean, fulltext
from prism.lib.vectors import unpack, dot
from prism.repositories.knowledge import KnowledgeBase

_TEMPLATES = Path(__file__).resolve().parent / "templates"
_HTML_TMPL = Environment(loader=FileSystemLoader(str(_TEMPLATES)), autoescape=True,
                         trim_blocks=True, lstrip_blocks=True).get_template("brief.html.j2")
_TXT_TMPL = Environment(loader=FileSystemLoader(str(_TEMPLATES)), autoescape=False,
                        trim_blocks=True, lstrip_blocks=True).get_template("brief.txt.j2")

_ACTIONS = ("up", "down", "save", "click")
_LESSON_SYSTEM = (
    "You are the editor of a daily LEARNING brief for a reader who wants to use AI/LLMs better. "
    "Turn the items into cards that TEACH, not summaries.\n"
    "First write THEME: one short line (<=14 words) naming the throughline across today's items — "
    "the pattern a curious reader should notice (no hype, only what the items show).\n"
    "Then for EACH item write a card with two fields:\n"
    "  lesson: 1-2 sentences — the concrete takeaway/technique/insight to apply or understand "
    "(lead with the 'how'/'so what'; for a personal account, surface the craft — the prompt, "
    "instruction, or workflow choice — as the lesson). Self-contained.\n"
    "  try: ONE imperative line a reader could actually do in ~30 seconds to feel the idea "
    "(a prompt to test, a setting to flip, a question to ask the model). Empty string if the "
    "item genuinely has nothing to try (news/release).\n"
    "Be concrete, non-hyped, grounded in the provided text; never invent specifics. Return "
    "ONLY JSON: {\"theme\":\"<line>\",\"cards\":[{\"id\":<int>,\"lesson\":\"..\",\"try\":\"..\"}, "
    "...]} for every id."
)

class BriefBuilder:
    def __init__(self, kb: KnowledgeBase, endpoint: str, model: str):
        self.kb = kb
        self.endpoint = endpoint
        self.model = model

    def build(self, lens: str, items: list) -> Brief:
        blurb = [(it.id, it.title, fulltext(it.url) or it.summary) for it in items]
        theme, cards = self._lessons(blurb)
        connections = self._connections(lens, items)
        return Brief(theme=theme, cards=cards, connections=connections)

    def _lessons(self, items: list[tuple]) -> tuple[str, dict[int, Card]]:
        if not self.endpoint:
            return "", {}
        try:
            client = foundry.openai_client(self.endpoint)
        except Exception as e:
            print(f"email: lesson client failed ({e}); sending titles only")
            return "", {}
        listing = "\n\n".join(
            f"[{i}] {t}\n{clean(s)}" if clean(s) else f"[{i}] {t}" for i, t, s in items)
        try:
            resp = client.chat.completions.create(
                model=self.model,
                messages=[{"role": "system", "content": _LESSON_SYSTEM},
                          {"role": "user", "content": listing}],
                temperature=0.3, response_format={"type": "json_object"}, max_tokens=1800)
            foundry.log_usage("email", resp)
            data = json.loads(resp.choices[0].message.content)
            cards = {int(c["id"]): Card(lesson=str(c.get("lesson", "")).strip(),
                                        try_it=str(c.get("try", "")).strip())
                     for c in data.get("cards", [])}
            return str(data.get("theme", "")).strip(), cards
        except Exception as e:
            print(f"email: lesson generation failed ({e}); sending titles only")
            return "", {}

    def _connections(self, lens: str, items: list,
                     min_cos: float = 0.62) -> dict[int, tuple[str, str]]:
        today_ids = [it.id for it in items]
        if not today_ids:
            return {}
        today_vecs: dict[int, list[float]] = {}
        for iid in today_ids:
            b = self.kb.embedding_of(iid)
            if b:
                today_vecs[iid] = unpack(b)
        if not today_vecs:
            return {}
        past = self.kb.sent_with_embeddings(lens, set(today_ids))
        if not past:
            return {}
        pairs = []
        for iid, tvec in today_vecs.items():
            for pid, title, url, pvec in past:
                c = dot(tvec, unpack(pvec))
                if c >= min_cos:
                    pairs.append((c, iid, pid, title, url))
        pairs.sort(reverse=True)
        out: dict[int, tuple[str, str]] = {}
        used_today: set[int] = set()
        used_past: set[int] = set()
        for _c, iid, pid, title, url in pairs:
            if iid in used_today or pid in used_past:
                continue
            out[iid] = (title, url)
            used_today.add(iid)
            used_past.add(pid)
        return out

    @staticmethod
    def render(items: list, brief: Brief, feedback_url: str = "",
               tokens: dict[int, dict[str, str]] | None = None,
               unsubscribe_url: str = "", preference_url: str = "",
               saved_url: str = "") -> tuple[str, str]:
        tokens = tokens or {}
        fb = bool(feedback_url and tokens)
        rows = []
        for idx, it in enumerate(items, 1):
            card = brief.cards.get(it.id)
            links = ({a: f"{feedback_url}?t={tokens[it.id][a]}"
                      for a in ("up", "down", "save", "click")} if fb else {})
            reasons = [str(getattr(r, "text", "")).strip()
                       for r in getattr(it, "reasons", ()) if getattr(r, "text", "")]
            rows.append({
                "idx": idx, "title": it.title, "url": it.url,
                "lesson": card.lesson if card else "",
                "try_it": card.try_it if card else "",
                "conn": brief.connections.get(it.id),
                "reasons": reasons,
                "src": links.get("click", it.url) if fb else it.url,
                "up": links.get("up"), "down": links.get("down"), "save": links.get("save"),
                "fb": fb,
            })
        ctx = {
            "theme": brief.theme,
            "rows": rows,
            "unsubscribe": unsubscribe_url,
            "preferences": preference_url,
            "saved": saved_url,
        }
        return _TXT_TMPL.render(**ctx).strip() + "\n", _HTML_TMPL.render(**ctx)
