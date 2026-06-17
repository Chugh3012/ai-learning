"""DraftSink — on-demand content sink: produces a kit per selected item via the profile's FORMAT."""
from __future__ import annotations

from ai_scout.services.delivery.sink import Sink, DeliveryContext


class DraftSink(Sink):
    """Deterministic selection (no explore wildcard on a production slot). Delegates to the
    ContentProducer; the Orchestrator owns sent:<lens> marking on success."""
    explore_ratio = 0.0

    def deliver(self, ctx: DeliveryContext) -> bool:
        return ctx.producer.produce(ctx.profile, ctx.items) > 0
