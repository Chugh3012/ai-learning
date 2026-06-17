from __future__ import annotations

from ai_scout.services.delivery.delivery_sink import DeliverySink
from ai_scout.services.delivery.sink import DeliveryContext

def send_email(settings, to: str, subject: str, plain: str, body_html: str) -> bool:
    acs_endpoint = settings.acs_endpoint
    sender = settings.email_sender
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
            "content": {"subject": subject, "plainText": plain, "html": body_html},
        }).result()
        return True
    except Exception as e:
        print(f"deliver: email send failed ({e})")
        return False

class EmailSink(DeliverySink):
    def _notify(self, ctx: DeliveryContext, plain: str, body_html: str, rows: list[tuple]) -> bool:
        to = ctx.settings.email_address(ctx.profile.email_var)
        subject = f"ai-scout \u2014 {len(rows)} new ways to use AI"
        return send_email(ctx.settings, to, subject, plain, body_html)
