from __future__ import annotations

import json
import time

from prism.lib import foundry
from prism.lib.text import clean
from prism.lib.topics import DEFAULT_TOPIC, list_topics, load_pack
from prism.repositories.knowledge import KnowledgeBase

SCORE_SCALE = 100
BATCH = 25

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

    def score_batch(self, rows: list[tuple[int, str, str]], system: str) -> dict[int, int]:
        listing = "\n\n".join(
            f"[{i}] {t[:160]}" + (f"\n{clean(s, 300)}" if clean(s, 300) else "")
            for i, t, s in rows
        )
        resp = self.client().chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": f"Rank and rate these {len(rows)} items:\n{listing}"},
            ],
            temperature=0,
            response_format={"type": "json_object"},
            max_tokens=900,
        )
        foundry.log_usage("rank", resp, self.model)
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
        try:
            self.client()
        except Exception as e:
            print(f"rank: skipped (client init failed: {e})")
            return 0
        now = int(time.time())
        scored = 0
        for topic_id in list_topics() or [DEFAULT_TOPIC]:
            pack = load_pack(topic_id)
            rows = self.kb.unscored_recent(days, max_items, topic_id)
            if not rows:
                continue
            for start in range(0, len(rows), BATCH):
                batch = rows[start:start + BATCH]
                try:
                    scores = self.score_batch(batch, pack.rubric)
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
