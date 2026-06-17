"""BriefBuilder — turns the day's picks into a LEARNING BRIEF (theme + teaching cards + connections)
and renders it to plain text + HTML for the delivery sinks.

`build()` makes one batched Foundry call for the throughline + per-item lesson/try, and a
pure-stdlib pass over the embedding table for connect-the-dots; both degrade gracefully to empty.
`render()` is pure presentation. Depends on a KnowledgeBase (DI).
"""
from __future__ import annotations

import html
import json

from ai_scout.domain.brief import Brief, Card
from ai_scout.lib import foundry
from ai_scout.lib.text import clean, fulltext
from ai_scout.lib.vectors import unpack, dot
from ai_scout.repositories.knowledge import KnowledgeBase

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
        except Exception as e:  # noqa: BLE001
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
        except Exception as e:  # noqa: BLE001
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
               tokens: dict[int, dict[str, str]] | None = None) -> tuple[str, str]:
        """Return (plain_text, html) for the learning brief. Pure presentation; degrades when
        fields are empty. `items` are ScoredItem; tokens map item_id->action->token."""
        tokens = tokens or {}
        connections = brief.connections or {}
        fb = bool(feedback_url and tokens)

        def link(item_id: int, action: str) -> str:
            return f"{feedback_url}?t={tokens[item_id][action]}"

        text_lines: list[str] = []
        html_lines = [
            '<div style="font-family:system-ui,Segoe UI,Arial,sans-serif;max-width:640px">',
            '<h2 style="margin:0 0 4px">ai-scout \u2014 today\u2019s learning brief</h2>',
        ]
        if brief.theme:
            text_lines.append(f"Today's throughline: {brief.theme}\n")
            html_lines.append(
                f'<p style="color:#0a66c2;font-size:14px;font-weight:600;margin:0 0 16px">'
                f'\u2728 {html.escape(brief.theme)}</p>')
        else:
            html_lines.append('<p style="color:#666;margin:0 0 16px">New ways to use AI, ranked for you.</p>')

        for idx, it in enumerate(items, 1):
            item_id, title, url = it.id, it.title, it.url
            card = brief.cards.get(item_id)
            lesson = card.lesson if card else ""
            try_it = card.try_it if card else ""
            conn = connections.get(item_id)
            src = link(item_id, "click") if fb else url

            text_lines.append(f"{idx}. {title}")
            if lesson:
                text_lines.append(f"   \U0001f4a1 {lesson}")
            if try_it:
                text_lines.append(f"   \U0001f527 Try: {try_it}")
            if conn:
                text_lines.append(f"   \u21aa Related: {conn[0]}")
            text_lines.append(f"   {url}")
            if fb:
                text_lines.append(
                    f"   feedback: \U0001f44d {link(item_id, 'up')}  |  \U0001f44e "
                    f"{link(item_id, 'down')}  |  \u2b50 {link(item_id, 'save')}")
            text_lines.append("")

            row = [
                '<div style="margin:0 0 22px;padding:0 0 16px;border-bottom:1px solid #ececec">',
                '<div style="font-weight:600;font-size:16px;color:#111;line-height:1.35">'
                f'<span style="color:#0a66c2">{idx}.</span> {html.escape(title)}</div>',
            ]
            if lesson:
                row.append('<div style="color:#333;font-size:14px;line-height:1.55;margin:8px 0">'
                           f'\U0001f4a1 {html.escape(lesson)}</div>')
            if try_it:
                row.append('<div style="background:#eef4ff;border-left:3px solid #0a66c2;'
                           'padding:8px 12px;margin:8px 0;font-size:13px;color:#0a3d6e;border-radius:3px">'
                           f'\U0001f527 <b>Try:</b> {html.escape(try_it)}</div>')
            row.append(
                '<div style="margin:8px 0 0;font-size:13px">'
                f'<a href="{html.escape(src)}" style="color:#0a66c2;text-decoration:none;font-weight:600">'
                'Read the source \u2192</a></div>')
            if conn:
                row.append('<div style="color:#999;font-size:12px;margin:6px 0 0">'
                           f'\u21aa Related to an earlier pick: {html.escape(conn[0])}</div>')
            if fb:
                row.append(
                    '<div style="margin-top:10px;font-size:13px">'
                    f'<a href="{html.escape(link(item_id, "up"))}" style="text-decoration:none;margin-right:16px">\U0001f44d more</a>'
                    f'<a href="{html.escape(link(item_id, "down"))}" style="text-decoration:none;margin-right:16px">\U0001f44e less</a>'
                    f'<a href="{html.escape(link(item_id, "save"))}" style="text-decoration:none">\u2b50 save</a>'
                    '</div>')
            row.append('</div>')
            html_lines.append("".join(row))

        html_lines.append('<p style="color:#999;font-size:12px">ai-scout \u00b7 daily learning brief</p></div>')
        return "\n".join(text_lines), "\n".join(html_lines)
