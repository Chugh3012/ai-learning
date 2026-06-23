from __future__ import annotations

import time

from prism.lib import foundry
from prism.lib.text import clean
from prism.lib.vectors import pack, normalize
from prism.repositories.knowledge import KnowledgeBase

BATCH = 128
DIMS = 256

class Embedder:
    def __init__(self, kb: KnowledgeBase, endpoint: str, deployment: str):
        self.kb = kb
        self.endpoint = endpoint
        self.deployment = deployment

    def embed_unembedded(self, max_items: int) -> int:
        if not self.endpoint:
            return 0
        rows = self.kb.unembedded_ranked(max_items)
        if not rows:
            return 0
        now = int(time.time())
        done = 0
        for start in range(0, len(rows), BATCH):
            batch = rows[start:start + BATCH]
            texts = [f"{t}\n{clean(s, 1000)}" if clean(s, 1000) else str(t) for _, t, s in batch]
            try:
                vecs = foundry.embed(self.endpoint, self.deployment, texts, DIMS)
            except Exception as e:
                print(f"embed: batch failed, stopping ({e})")
                break
            self.kb.add_embeddings([(batch[i][0], pack(vecs[i])) for i in range(len(batch))], now)
            self.kb.commit()
            done += len(batch)
        print(f"embed: embedded {done} items")
        return done

    def embed_interest(self, interest: str) -> list[float] | None:
        if not (self.endpoint and interest):
            return None
        try:
            return normalize(foundry.embed(self.endpoint, self.deployment, [interest], DIMS)[0])
        except Exception as e:
            print(f"embed: interest embed failed ({e}); no interest steering this run")
            return None
