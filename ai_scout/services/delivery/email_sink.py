"""EmailSink — delivers the learning brief via Azure Communication Services (passwordless)."""
from __future__ import annotations

from ai_scout.services.delivery.delivery_sink import DeliverySink
from ai_scout.services.delivery.sink import DeliveryContext


class EmailSink(DeliverySink):
    def _emit(self, ctx: DeliveryContext, plain: str, body_html: str, rows: list[tuple]) -> bool:
        s, p = ctx.settings, ctx.profile
        acs_endpoint = s.acs_endpoint
        sender = s.email_sender
        to = s.email_address(p.email_var)
        if not (acs_endpoint and sender and to):
            print("deliver: email channel not configured for recipient; skipped")
            return False
        try:
            from azure.communication.email import EmailClient
            from azure.identity import DefaultAzureCredential
            client = EmailClient(acs_endpoint, DefaultAzureCredential())
            client.begin_send({
                "senderAddress": sender,
                "recipients": {"to": [{"address": to}]},
                "content": {"subject": f"ai-scout \u2014 {len(rows)} new ways to use AI",
                            "plainText": plain, "html": body_html},
            }).result()
            return True
        except Exception as e:  # noqa: BLE001 — optional stage, never break the pipeline
            print(f"deliver: email send failed ({e})")
            return False
