from __future__ import annotations

import json

from prism.lib import foundry
from prism.lib.text import clean

_SYSTEM = (
    "You are the scriptwriter for a daily VERTICAL VIDEO called 'AI Radar' that gives people fast, "
    "accurate updates on AI. For EACH item write a card with three fields:\n"
    "  headline: a punchy, specific hook of AT MOST 7 words. Concrete and accurate — no clickbait, "
    "no hype, no trailing punctuation. Name the actual thing (model/tool/finding).\n"
    "  line: ONE plain-English sentence (<=22 words) saying what is new and why it matters to "
    "someone building or using AI. This is spoken aloud, so make it natural.\n"
    "  query: 2 to 4 plain visual keywords for stock B-ROLL footage matching this item — concrete, "
    "filmable scenes (e.g. 'robot arm factory', 'data center servers', 'person coding laptop'). No "
    "brand names, no text.\n"
    "Strip any feed artifacts (e.g. 'Discussion | Link', 'Comments', 'Announce Type', 'Abstract:'). "
    "Be faithful to the provided text; never invent specifics. Also write an overall 'hook' of AT "
    "MOST 5 words for the intro card. Return ONLY JSON: "
    "{\"hook\":\"<line>\",\"items\":[{\"id\":<int>,\"headline\":\"..\",\"line\":\"..\","
    "\"query\":\"..\"}, ...]} for every id."
)

_DEEP_SYSTEM = (
    "You are scripting a SHORT vertical EXPLAINER video (about 45-60 seconds) on ONE AI story. It "
    "must be CATCHY (a scroll-stopping hook) yet EXPLANATORY (the viewer actually learns what it is "
    "and why it matters). Write 5 to 6 beats, each ONE natural spoken sentence:\n"
    "  beat 1 = a punchy HOOK (a bold claim or question, <=12 words) that makes people stop.\n"
    "  middle beats = explain WHAT it is, WHY it matters, and ONE concrete detail or how it works "
    "(each <=24 words, plain English, accurate to the source).\n"
    "  last beat = the takeaway or what it means next.\n"
    "For EACH beat also give 'query': 2-4 plain visual keywords for stock b-roll (filmable scenes, "
    "no brand names, no on-screen text). Be faithful to the source; never invent specifics. Also "
    "give a short 'hook' phrase (<=5 words) for the title card. Return ONLY JSON: "
    "{\"hook\":\"..\",\"beats\":[{\"text\":\"..\",\"query\":\"..\"}, ...]}."
)

class ReelScripter:
    """LLM pass that rewrites raw KB items into punchy reel cards. Graceful: returns ('', {}) when
    the model is unconfigured or fails, so the caller falls back to the raw title/summary."""

    def __init__(self, endpoint: str, model: str):
        self.endpoint = endpoint
        self.model = model

    def script(self, items: list[tuple]) -> tuple[str, dict[int, tuple[str, str, str]]]:
        # items: list of (id, title, summary). Returns (hook, {id: (headline, line, query)}).
        if not self.endpoint or not items:
            return "", {}
        try:
            client = foundry.openai_client(self.endpoint)
        except Exception as e:
            print(f"reel: script client failed ({e}); using raw titles")
            return "", {}
        listing = "\n\n".join(
            f"[{i}] {t}\n{clean(s)}" if clean(s) else f"[{i}] {t}" for i, t, s in items)
        try:
            resp = client.chat.completions.create(
                model=self.model,
                messages=[{"role": "system", "content": _SYSTEM},
                          {"role": "user", "content": listing}],
                temperature=0.4, response_format={"type": "json_object"}, max_tokens=1100)
            foundry.log_usage("reel", resp, self.model)
            data = json.loads(resp.choices[0].message.content)
            cards = {int(c["id"]): (str(c.get("headline", "")).strip(),
                                    str(c.get("line", "")).strip(),
                                    str(c.get("query", "")).strip())
                     for c in data.get("items", [])}
            return str(data.get("hook", "")).strip(), cards
        except Exception as e:
            print(f"reel: script generation failed ({e}); using raw titles")
            return "", {}

    def script_deep(self, title: str, body: str) -> tuple[str, list[tuple[str, str]]]:
        # One article -> (hook, [(spoken_beat, broll_query), ...]). Catchy + explanatory.
        if not self.endpoint:
            return "", []
        try:
            client = foundry.openai_client(self.endpoint)
        except Exception as e:
            print(f"reel: deep script client failed ({e})")
            return "", []
        try:
            resp = client.chat.completions.create(
                model=self.model,
                messages=[{"role": "system", "content": _DEEP_SYSTEM},
                          {"role": "user", "content": f"{title}\n\n{clean(body, 4000)}"}],
                temperature=0.5, response_format={"type": "json_object"}, max_tokens=1300)
            foundry.log_usage("reel-deep", resp, self.model)
            data = json.loads(resp.choices[0].message.content)
            beats = [(str(b.get("text", "")).strip(), str(b.get("query", "")).strip())
                     for b in data.get("beats", []) if str(b.get("text", "")).strip()]
            return str(data.get("hook", "")).strip(), beats
        except Exception as e:
            print(f"reel: deep script generation failed ({e})")
            return "", []
