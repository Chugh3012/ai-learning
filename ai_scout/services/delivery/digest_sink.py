"""DigestSink — writes the learning brief to a dated digest file the maintainer agent reads."""
from __future__ import annotations

from datetime import datetime, timezone

from ai_scout.lib.config import DIGESTS_DIR
from ai_scout.services.delivery.delivery_sink import DeliverySink
from ai_scout.services.delivery.sink import DeliveryContext


class DigestSink(DeliverySink):
    def _emit(self, ctx: DeliveryContext, plain: str, body_html: str, rows: list[tuple]) -> bool:
        p = ctx.profile
        DIGESTS_DIR.mkdir(exist_ok=True)
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        out = DIGESTS_DIR / f"{p.filesafe_lens}-{today}.md"
        item_ids = [r[0] for r in rows]
        header = (f"# ai-scout \u2014 {p.label} \u2014 {today}\n\n"
                  f"_{len(rows)} items from the shared ranking, reordered by this profile's "
                  f"feedback. Read, act if useful (the commit is the record), then ignore next "
                  f"cycle._\n\n")
        footer = f"\n\n<!-- items: {','.join(str(i) for i in item_ids)} -->\n"
        out.write_text(header + plain + footer, encoding="utf-8")
        print(f"deliver: wrote {out.relative_to(DIGESTS_DIR.parent)}")
        return True
