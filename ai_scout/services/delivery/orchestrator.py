from __future__ import annotations

import time

from ai_scout.repositories.knowledge import KnowledgeBase
from ai_scout.repositories.registry import UserRegistry
from ai_scout.repositories.feedback import FeedbackStore
from ai_scout.services.brief_builder import BriefBuilder
from ai_scout.services.embedder import Embedder
from ai_scout.services.selector import Selector, interest_weight
from ai_scout.services.delivery.sink import Sink, DeliveryContext
from ai_scout.services.delivery.email_sink import EmailSink
from ai_scout.services.delivery.digest_sink import DigestSink

_SINKS: dict[str, type[Sink]] = {"email": EmailSink, "digest": DigestSink}

def make_sink(channel: str) -> Sink:
    cls = _SINKS.get(channel)
    if cls is None:
        raise ValueError(f"unknown delivery channel '{channel}'")
    return cls()

class Orchestrator:
    def __init__(self, kb: KnowledgeBase, registry: UserRegistry, embedder: Embedder,
                 selector: Selector, brief_builder: BriefBuilder,
                 feedback_store: FeedbackStore, blob, settings, metrics=None):
        self.kb = kb
        self.registry = registry
        self.embedder = embedder
        self.selector = selector
        self.brief_builder = brief_builder
        self.feedback_store = feedback_store
        self.blob = blob
        self.settings = settings
        self.metrics = metrics

    def run(self, targets: set[str] | None = None) -> int:
        weight = interest_weight()
        now = int(time.time())
        total = 0
        for user in self.registry.users:
            for p in user.profiles:
                if targets is not None:
                    if p.lens not in targets:
                        continue
                elif not p.cadence.is_due(self.kb.last_sent_ts(p.lens), now):
                    continue
                sink = make_sink(p.channel)
                interest_vec = self.embedder.embed_interest(p.interest)
                items = self.selector.select(p.lens, p.top, p.min_score, interest_vec, weight)
                if not items:
                    if self.metrics is not None:
                        self.metrics.add("delivered", 0, lens=p.lens, channel=p.channel)
                    print(f"deliver: nothing clears {p.lens} (min_score={p.min_score:g}) — quiet")
                    continue
                ctx = DeliveryContext(p, items, self.settings, self.brief_builder,
                                      self.feedback_store, self.blob)
                if sink.deliver(ctx):
                    self.kb.mark_sent(p.lens, [it.id for it in items])
                    total += len(items)
                    if self.metrics is not None:
                        self.metrics.add("delivered", len(items), lens=p.lens, channel=p.channel)
                        scores = [float(getattr(it, "score", 0) or 0) for it in items]
                        if scores:
                            self.metrics.add("relevance_delivered", sum(scores) / len(scores),
                                             lens=p.lens, channel=p.channel)
                    print(f"deliver: {len(items)} -> {p.lens} ({p.channel})")
        return total
