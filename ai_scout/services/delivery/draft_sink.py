from __future__ import annotations

from ai_scout.services.delivery.sink import Sink, DeliveryContext

class DraftSink(Sink):
    explore_ratio = 0.0

    def deliver(self, ctx: DeliveryContext) -> bool:
        return ctx.producer.produce(ctx.profile, ctx.items) > 0
