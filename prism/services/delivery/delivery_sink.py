from __future__ import annotations

from datetime import datetime, timezone

from prism.lib.config import SCRATCH_DIR
from prism.domain.edition import Edition
from prism.services.brief_builder import BriefBuilder
from prism.services.delivery.sink import Sink, DeliveryContext

class DeliverySink(Sink):

    def deliver(self, ctx: DeliveryContext) -> bool:
        p = ctx.profile
        rows = [(it.id, it.title, it.url) for it in ctx.items]
        brief = ctx.brief_builder.build(p.lens, ctx.items)
        feedback_url = ctx.settings.feedback_url
        tokens = ctx.feedback_store.mint_tokens(p.lens, rows) if feedback_url else {}
        unsub = self._unsubscribe_url(ctx)
        pref = self._preference_url(ctx)
        saved = self._saved_url(ctx)
        try:
            learned = ", ".join(ctx.brief_builder.kb.taste_summary(p.lens))
        except Exception:
            learned = ""
        plain, body_html = BriefBuilder.render(
            ctx.items, brief, feedback_url, tokens, unsub, pref, saved, learned)
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        header = (f"# ai-scout — {p.label} — {today}\n\n"
                  f"_{len(rows)} items from the shared ranking, reordered by this profile's "
                  f"feedback._\n\n")
        footer = f"\n\n{Edition(p.lens, [r[0] for r in rows]).footer()}\n"
        self._write_digest(ctx, f"{p.filesafe_lens}-{today}.md", header + plain + footer)
        return self._notify(ctx, plain, body_html, rows)

    @staticmethod
    def _unsubscribe_url(ctx: DeliveryContext) -> str:
        base = getattr(ctx.settings, "unsubscribe_url", "")
        token = getattr(ctx.profile, "unsubscribe_token", "")
        return f"{base}?t={token}" if (base and token) else ""

    @staticmethod
    def _preference_url(ctx: DeliveryContext) -> str:
        base = getattr(ctx.settings, "preference_url", "")
        token = getattr(ctx.profile, "unsubscribe_token", "")
        profile_id = getattr(ctx.profile, "id", "")
        if not (base and token):
            return ""
        suffix = f"?t={token}"
        if profile_id:
            suffix += f"&p={profile_id}"
        return base + suffix

    @staticmethod
    def _saved_url(ctx: DeliveryContext) -> str:
        base = getattr(ctx.settings, "saved_url", "")
        token = getattr(ctx.profile, "unsubscribe_token", "")
        profile_id = getattr(ctx.profile, "id", "")
        if not (base and token):
            return ""
        suffix = f"?t={token}"
        if profile_id:
            suffix += f"&p={profile_id}"
        return base + suffix

    def _write_digest(self, ctx: DeliveryContext, name: str, md: str) -> None:
        if ctx.blob is not None and ctx.blob.enabled:
            ctx.blob.put_text(f"digests/{name}", md)
            print(f"deliver: wrote digests/{name} to Blob")
            return
        d = SCRATCH_DIR / "digests"
        d.mkdir(parents=True, exist_ok=True)
        (d / name).write_text(md, encoding="utf-8")
        print(f"deliver: wrote .scratch/digests/{name} (Blob not configured)")

    def _notify(self, ctx: DeliveryContext, plain: str, body_html: str, rows: list[tuple]) -> bool:
        return True
