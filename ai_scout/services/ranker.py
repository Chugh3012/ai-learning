from __future__ import annotations

import json
import time

from ai_scout.lib import foundry
from ai_scout.lib.text import clean
from ai_scout.repositories.knowledge import KnowledgeBase

SCORE_SCALE = 100
BATCH = 25
SYSTEM = (
    "You are the curator of a daily AI/LLM brief. Every item already comes from an AI-focused "
    "source, so your job is NOT 'is this about AI' — it is 'is this SIGNAL worth a curious "
    "reader's attention, or NOISE?'. Reward signal broadly; demote noise hard. Rate each 0-100.\n"
    "FIRST GATE: if an item is genuinely NOT about AI/ML/LLMs (generic software, a game, an "
    "unrelated topic), score it 0-10 no matter how interesting.\n"
    "SIGNAL is any of: a concrete technique / tool / workflow / prompt-or-instruction craft you "
    "could use; a genuinely significant development you'd want to know about — a new model or "
    "product, a real new capability, or a notable shift; a clear explanation of how AI works or "
    "behaves; or a sharp idea about USING or UNDERSTANDING AI. NOISE is: version-bump / changelog "
    "churn, funding / PR / marketing, hype with nothing to learn, rehashed news, AI merely applied "
    "inside an unrelated domain (medicine, finance, biology, pure math), or pure ML / architecture "
    "/ math theory with no usable or significant takeaway.\n"
    "Calibrate to this rubric and USE THE FULL RANGE — most are NOT a 90:\n"
    "  85-100: high signal — a usable technique/craft you could act on now, OR a genuinely "
    "significant AI development (a new model, real new capability, or notable shift) worth knowing.\n"
    "  65-84:  solid signal — a useful applied insight, a notable real product/release, a "
    "how-someone-actually-uses-AI story, or a clear explanation of how AI works or behaves.\n"
    "  40-64:  mild signal — on-topic but general, early, shallow, or merely fun/interesting with "
    "little to take away.\n"
    "  15-39:  low signal — incremental version/changelog churn, AI applied inside an unrelated "
    "domain, or pure ML/math/architecture theory with no usable or significant takeaway.\n"
    "  0-14:   noise — non-AI, pure funding/policy/PR, or hype with nothing to learn.\n"
    "Be BROAD about what counts as signal (useful, significant, OR insightful — not just how-tos) "
    "but STRICT about noise. Spread the scores so the batch is genuinely ranked, not clustered. "
    "Judge the whole batch relative to each other. Return ONLY compact JSON: "
    "{\"scores\":[{\"id\":<int>,\"s\":<0-100>}, ...]} for every id given."
)

class Ranker:

    def __init__(self, kb: KnowledgeBase | None, endpoint: str, model: str):
        self.kb = kb
        self.endpoint = endpoint
        self.model = model
        self._client = None

    def client(self):
        if self._client is None:
            self._client = foundry.openai_client(self.endpoint)
        return self._client

    def score_batch(self, rows: list[tuple[int, str, str]]) -> dict[int, int]:
        listing = "\n\n".join(
            f"[{i}] {t[:160]}" + (f"\n{clean(s, 300)}" if clean(s, 300) else "")
            for i, t, s in rows
        )
        resp = self.client().chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": SYSTEM},
                {"role": "user", "content": f"Rank and rate these {len(rows)} items:\n{listing}"},
            ],
            temperature=0,
            response_format={"type": "json_object"},
            max_tokens=900,
        )
        foundry.log_usage("rank", resp)
        data = json.loads(resp.choices[0].message.content)
        out: dict[int, int] = {}
        for r in data.get("scores", []):
            try:
                out[int(r["id"])] = max(0, min(SCORE_SCALE, int(r["s"])))
            except (KeyError, ValueError, TypeError):
                continue
        return out

    def score_unscored(self, days: int, max_items: int) -> int:
        if not self.endpoint:
            return 0
        rows = self.kb.unscored_recent(days, max_items)
        if not rows:
            return 0
        try:
            self.client()
        except Exception as e:
            print(f"rank: skipped (client init failed: {e})")
            return 0
        now = int(time.time())
        scored = 0
        for start in range(0, len(rows), BATCH):
            batch = rows[start:start + BATCH]
            try:
                scores = self.score_batch(batch)
            except Exception as e:
                print(f"rank: batch failed, stopping ({e})")
                break
            for item_id, _t, _s in batch:
                if item_id in scores:
                    self.kb.add_relevance(item_id, float(scores[item_id]), now)
                    scored += 1
            self.kb.commit()
        print(f"rank: scored {scored} items")
        return scored
