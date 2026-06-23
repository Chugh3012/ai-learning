from __future__ import annotations

import time

from prism.repositories.knowledge import KnowledgeBase
from prism.repositories.registry import UserRegistry
from prism.repositories.feedback import FeedbackStore
from prism.services.brief_builder import BriefBuilder
from prism.services.embedder import Embedder
from prism.services.selector import Selector, interest_weight
from prism.services.delivery.sink import Sink, DeliveryContext
from prism.services.delivery.email_sink import EmailSink
from prism.services.delivery.digest_sink import DigestSink

_SINKS: dict[str, type[Sink]] = {"email": EmailSink, "digest": DigestSink}

def make_sink(channel: str) -> Sink:
    cls = _SINKS.get(channel)
    if cls is None:
        raise ValueError(f"unknown delivery channel '{channel}'")
    return cls()

class Orchestrator:
    def __init__(self, kb: KnowledgeBase, registry: UserRegistry, embedder: Embedder,
                 selector: Selector, brief_builder: BriefBuilder,
                 feedback_store: FeedbackStore, blob, settings, metrics=None, taste=None):
        self.kb = kb
        self.registry = registry
        self.embedder = embedder
        self.selector = selector
        self.brief_builder = brief_builder
        self.feedback_store = feedback_store
        self.blob = blob
        self.settings = settings
        self.metrics = metrics
        self.taste = taste

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
                user_vec = self.taste.user_vector(p.lens, interest_vec) if self.taste else interest_vec
                items = self.selector.select(p.lens, p.top, p.min_score, user_vec, weight,
                                             topic_id=p.topic_id)
                if not items:
                    if self.metrics is not None:
                        self.metrics.add("delivered", 0, lens=p.lens, channel=p.channel,
                                         topic=p.topic_id)
                    print(f"deliver: nothing clears {p.lens} (min_score={p.min_score:g}) — quiet")
                    continue
                ctx = DeliveryContext(p, items, self.settings, self.brief_builder,
                                      self.feedback_store, self.blob)
                if sink.deliver(ctx):
                    self.kb.mark_sent(p.lens, [it.id for it in items])
                    total += len(items)
                    if self.metrics is not None:
                        self.metrics.add("delivered", len(items), lens=p.lens, channel=p.channel,
                                         topic=p.topic_id)
                        scores = [float(getattr(it, "score", 0) or 0) for it in items]
                        if scores:
                            self.metrics.add("relevance_delivered", sum(scores) / len(scores),
                                             lens=p.lens, channel=p.channel, topic=p.topic_id)
                    print(f"deliver: {len(items)} -> {p.lens} ({p.channel})")
        if targets is None:
            self._cache_welcome_edition(weight)
        return total

    def _cache_welcome_edition(self, weight) -> None:
        # Render a generic top-5 edition and stash it where the subscribe Function can read
        # it, so a brand-new user gets their first email the instant they confirm (no wait
        # for the next daily run). Stable lens (never marked sent) => always current top 5.
        # Optional + graceful: no storage / nothing clears -> no-op.
        try:
            account = (getattr(self.settings, "subscriber_storage", "")
                       or getattr(self.settings, "feedback_storage", ""))
            if not account:
                return
            lens = "edition:welcome"
            interest_vec = self.embedder.embed_interest("")
            items = self.selector.select(lens, 5, 55, interest_vec, weight)
            if not items:
                print("deliver: no welcome edition cached (nothing clears) — quiet")
                return
            rows = [(it.id, it.title, it.url) for it in items]
            brief = self.brief_builder.build(lens, items)
            # No feedback buttons in the welcome: a brand-new user has no history to
            # personalize and the welcome lens is never reconciled into affinity, so those
            # controls would be inert. Their first daily edition carries working per-profile
            # feedback; the per-user unsubscribe link is added by the Function when it sends.
            plain, body_html = BriefBuilder.render(items, brief)
            from azure.data.tables import TableServiceClient, UpdateMode
            from azure.identity import DefaultAzureCredential
            svc = TableServiceClient(
                endpoint=f"https://{account}.table.core.windows.net",
                credential=DefaultAzureCredential())
            svc.create_table_if_not_exists("editions")
            svc.get_table_client("editions").upsert_entity({
                "PartitionKey": "edition", "RowKey": "welcome",
                "subject": f"Welcome to Chugh Vibes \u2014 today's top {len(rows)}",
                "plain": plain, "html": body_html, "ts": int(time.time()),
            }, mode=UpdateMode.REPLACE)
            print(f"deliver: cached welcome edition ({len(rows)} items)")
        except Exception as e:
            print(f"deliver: welcome edition cache skipped ({e})")

