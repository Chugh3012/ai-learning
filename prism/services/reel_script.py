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
    "You are writing a fun, fast 30-40s vertical video that explains ONE specific AI thing to a "
    "smart friend who is NOT a techie. Talk like a real person out loud -- contractions, 'you', "
    "warm and a little playful, never robotic. The viewer should get ONE concrete thing (what it is "
    "and why they'd care) and feel a 'wait, that's real?' moment worth sharing. Write 7 to 9 short "
    "spoken beats, each one line of 5-12 words. Beat 1 = a surprising, relatable HOOK. Then, in "
    "plain words: what it is, the one wild thing it does, and why you'd care or what you could do "
    "with it. End on a punchy line. NO jargon, NO bare acronyms, NO buzzwords (powerful, "
    "game-changing, revolutionary); if a thing has a technical name, explain it plainly or skip it. "
    "Specific and true to the source; never invent a number or fact. For EACH beat give 'query': "
    "2-4 filmable visual keywords (no brand names, no on-screen text). Also give a 'hook' phrase "
    "(<=5 words). Return ONLY JSON: {\"hook\":\"..\",\"beats\":[{\"text\":\"..\",\"query\":\"..\"}, ...]}."
)

class ReelScripter:
    """LLM pass that rewrites raw KB items into punchy reel cards. Graceful: returns ('', {}) when
    the model is unconfigured or fails, so the caller falls back to the raw title/summary."""

    def __init__(self, endpoint: str, model: str):
        self.endpoint = endpoint
        self.model = model

    def script(self, items: list[tuple], system: str = "") -> tuple[str, dict[int, tuple[str, str, str]]]:
        # items: list of (id, title, summary). Returns (hook, {id: (headline, line, query)}).
        # `system` = the creative brief (from a playbook); empty falls back to the built-in default.
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
                messages=[{"role": "system", "content": system or _SYSTEM},
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

    def script_deep(self, title: str, body: str, system: str = "") -> tuple[str, list[tuple[str, str]]]:
        # One article -> (hook, [(spoken_beat, broll_query), ...]). Catchy + explanatory.
        # `system` = the creative brief (from a playbook); empty falls back to the built-in default.
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
                messages=[{"role": "system", "content": system or _DEEP_SYSTEM},
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
