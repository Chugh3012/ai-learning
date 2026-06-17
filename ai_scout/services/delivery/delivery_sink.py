from __future__ import annotations

from abc import abstractmethod

from ai_scout.services.brief_builder import BriefBuilder
from ai_scout.services.delivery.sink import Sink, DeliveryContext

class DeliverySink(Sink):

    def deliver(self, ctx: DeliveryContext) -> bool:
        p = ctx.profile
        rows = [(it.id, it.title, it.url) for it in ctx.items]
        brief = ctx.brief_builder.build(p.lens, ctx.items)
        feedback_url = ctx.settings.feedback_url
        tokens = ctx.feedback_store.mint_tokens(p.lens, rows) if feedback_url else {}
        plain, body_html = BriefBuilder.render(ctx.items, brief, feedback_url, tokens)
        return self._emit(ctx, plain, body_html, rows)

    @abstractmethod
    def _emit(self, ctx: DeliveryContext, plain: str, body_html: str, rows: list[tuple]) -> bool:
        raise NotImplementedError
