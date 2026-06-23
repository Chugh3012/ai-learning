from __future__ import annotations

from prism.services.delivery.delivery_sink import DeliverySink
from prism.services.delivery.sink import DeliveryContext

def send_email(settings, to: str, subject: str, plain: str, body_html: str,
               unsubscribe_url: str = "") -> bool:
    acs_endpoint = settings.acs_endpoint
    sender = settings.email_sender
    if not (acs_endpoint and sender and to):
        print("deliver: email channel not configured for recipient; skipped")
        return False
    try:
        from azure.communication.email import EmailClient
        from azure.identity import DefaultAzureCredential
        client = EmailClient(acs_endpoint, DefaultAzureCredential())
        message = {
            "senderAddress": sender,
            "recipients": {"to": [{"address": to}]},
            "content": {"subject": subject, "plainText": plain, "html": body_html},
        }
        if unsubscribe_url:
            # RFC 8058 one-click unsubscribe (Gmail/Yahoo/Apple bulk-sender requirement).
            message["headers"] = {
                "List-Unsubscribe": f"<{unsubscribe_url}>",
                "List-Unsubscribe-Post": "List-Unsubscribe=One-Click",
            }
        client.begin_send(message).result()
        return True
    except Exception as e:
        print(f"deliver: email send failed ({e})")
        return False

class EmailSink(DeliverySink):
    def _notify(self, ctx: DeliveryContext, plain: str, body_html: str, rows: list[tuple]) -> bool:
        p = ctx.profile
        to = p.email or ctx.settings.email_address(p.email_var)
        subject = f"ai-scout \u2014 {len(rows)} new ways to use AI"
        return send_email(ctx.settings, to, subject, plain, body_html,
                          self._unsubscribe_url(ctx))
