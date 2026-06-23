from __future__ import annotations

from prism.lib import foundry
from prism.repositories.knowledge import KnowledgeBase

_SYSTEM = (
    "You write a short weekly recap for a reader of a daily brief. Given the titles they were "
    "sent this week, write 2-3 sentences: the throughline connecting them and the themes worth "
    "remembering. Be concrete and concise -- no preamble, no lists, just the recap prose."
)

class WeeklySynthesis:
    def __init__(self, kb: KnowledgeBase, endpoint: str, model: str):
        self.kb = kb
        self.endpoint = endpoint
        self.model = model
        self._client = None

    def client(self):
        if self._client is None:
            self._client = foundry.openai_client(self.endpoint)
        return self._client

    def recap(self, lens: str, days: int = 7) -> str:
        if not self.endpoint:
            return ""
        titles = self.kb.recent_sent_titles(lens, days)
        if len(titles) < 3:
            return ""
        listing = "\n".join(f"- {t}" for t in titles[:40])
        try:
            resp = self.client().chat.completions.create(
                model=self.model,
                messages=[{"role": "system", "content": _SYSTEM},
                          {"role": "user", "content": f"This week's reads:\n{listing}"}],
                temperature=0.3,
                max_tokens=200,
            )
            foundry.log_usage("synthesis", resp)
            return resp.choices[0].message.content.strip()
        except Exception as e:
            print(f"synthesis: skipped ({e})")
            return ""
