from __future__ import annotations

import hashlib
import html
import json
import logging
import os
import re
import secrets
import time

import azure.functions as func
from azure.core.exceptions import ResourceExistsError, ResourceNotFoundError
from azure.data.tables import TableServiceClient, UpdateMode
from azure.identity import DefaultAzureCredential

app = func.FunctionApp()

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_SUBSCRIBERS = "subscribers"
_RESEND_WINDOW = 600  # don't re-send a confirmation to the same address within 10 min

_ACTIONS: dict[str, tuple[str, float]] = {
    "up": ("vote", 1.0),
    "down": ("vote", -1.0),
    "save": ("save", 1.0),
    "click": ("click", 1.0),
}

_TABLE_SERVICE: TableServiceClient | None = None

def _tables() -> TableServiceClient:
    global _TABLE_SERVICE
    if _TABLE_SERVICE is None:
        account = os.environ["AzureWebJobsStorage__accountName"]
        _TABLE_SERVICE = TableServiceClient(
            endpoint=f"https://{account}.table.core.windows.net",
            credential=DefaultAzureCredential(),
        )
    return _TABLE_SERVICE

def _page(message: str, ok: bool = True) -> func.HttpResponse:
    mark = "✓" if ok else "—"
    accent = "#2438e0" if ok else "#6b6357"
    body = (
        '<!doctype html><html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        '<title>Chugh Vibes</title>'
        '<link rel="preconnect" href="https://fonts.googleapis.com">'
        '<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>'
        '<link href="https://fonts.googleapis.com/css2?family=Fraunces:opsz,wght@9..144,500;9..144,600&family=Inter:wght@400;500&display=swap" rel="stylesheet">'
        '</head><body style="margin:0;background:#f3efe4;color:#1a1712;'
        "font-family:Inter,system-ui,sans-serif;min-height:100vh;display:flex;"
        'align-items:center;justify-content:center">'
        '<div style="text-align:center;max-width:30rem;padding:2rem">'
        f'<div style="font-size:44px;line-height:1;color:{accent}">{mark}</div>'
        '<h1 style="font-family:Fraunces,Georgia,serif;font-weight:500;'
        f'font-size:2rem;letter-spacing:-.02em;margin:1rem 0 .5rem">{html.escape(message)}</h1>'
        '<p style="color:#6b6357;font-size:.95rem;margin:0">'
        'You can close this tab.</p>'
        '<p style="font-family:Fraunces,Georgia,serif;font-size:1.05rem;margin-top:2rem">'
        'chugh<span style="color:#2438e0">·</span>vibes</p>'
        '</div></body></html>'
    )
    return func.HttpResponse(body, mimetype="text/html", status_code=200)

def _json(status: int, ok: bool, message: str) -> func.HttpResponse:
    return func.HttpResponse(
        json.dumps({"ok": ok, "message": message}),
        status_code=status, mimetype="application/json",
    )

def _email_key(email: str) -> str:
    return hashlib.sha256(email.encode("utf-8")).hexdigest()

def _new_user_id() -> str:
    return "usr_" + secrets.token_hex(4)

def _subscribers():
    svc = _tables()
    try:
        svc.create_table_if_not_exists(_SUBSCRIBERS)
    except Exception:
        pass
    return svc.get_table_client(_SUBSCRIBERS)

def _api_base(req: func.HttpRequest) -> str:
    override = os.environ.get("SUBSCRIBE_API_BASE", "")
    if override:
        return override.rstrip("/")
    from urllib.parse import urlsplit
    parts = urlsplit(req.url)
    return f"https://{parts.netloc}/api"

def _confirm_email_html(hello: str, confirm_url: str) -> str:
    safe = html.escape(confirm_url, quote=True)
    return (
        '<div style="font-family:Inter,Segoe UI,Arial,sans-serif;background:#f3efe4;'
        'padding:32px;color:#1a1712">'
        '<div style="max-width:520px;margin:0 auto">'
        '<p style="font-family:Georgia,serif;font-size:20px;font-weight:600;margin:0 0 20px">'
        'chugh<span style="color:#2438e0">&middot;</span>vibes</p>'
        f'<p style="font-size:16px;margin:0 0 12px">{hello}</p>'
        '<p style="font-size:16px;line-height:1.5;margin:0 0 24px">'
        'Thanks for subscribing to <strong>Chugh Vibes</strong> — one sharp AI read a day. '
        'Confirm your email to start.</p>'
        f'<a href="{safe}" style="display:inline-block;background:#2438e0;color:#fff;'
        'text-decoration:none;font-weight:600;padding:13px 22px;border-radius:2px">'
        'Confirm subscription</a>'
        '<p style="font-size:13px;color:#6b6357;line-height:1.5;margin:20px 0 0">'
        'Button not working? Paste this link into your browser:<br>'
        f'<a href="{safe}" style="color:#1a29b8;word-break:break-all">{safe}</a></p>'
        '<p style="font-size:13px;color:#6b6357;line-height:1.5;margin:16px 0 0">'
        "If you didn't request this, just ignore this email — nothing will be sent.</p>"
        '</div></div>'
    )

def _acs_send(to: str, subject: str, plain: str, body_html: str) -> bool:
    endpoint = os.environ.get("ACS_ENDPOINT", "")
    sender = os.environ.get("EMAIL_SENDER", "")
    if not (endpoint and sender):
        logging.warning("email: ACS not configured; not sent")
        return False
    try:
        from azure.communication.email import EmailClient
        client = EmailClient(endpoint, DefaultAzureCredential())
        client.begin_send({
            "senderAddress": sender,
            "recipients": {"to": [{"address": to}]},
            "content": {"subject": subject, "plainText": plain, "html": body_html},
        }).result()
        return True
    except Exception:
        logging.exception("email: send failed")
        return False

def _send_confirmation(to: str, name: str, confirm_url: str) -> bool:
    hello = f"Hi {name}," if name else "Hi,"
    plain = (
        f"{hello}\n\n"
        "Thanks for subscribing to Chugh Vibes - one sharp AI read a day.\n\n"
        f"Confirm your subscription:\n{confirm_url}\n\n"
        "If you didn't request this, just ignore this email.\n"
    )
    return _acs_send(to, "Confirm your Chugh Vibes subscription", plain,
                     _confirm_email_html(html.escape(hello), confirm_url))

def _send_welcome(to: str) -> bool:
    # Fire the new user's first edition the moment they confirm, using the generic top-5
    # the pipeline cached. No cache yet (cold start) -> skip; they'll get the next daily run.
    try:
        ed = _tables().get_table_client("editions").get_entity("edition", "welcome")
    except Exception:
        logging.info("welcome: no cached edition yet; skipping instant send")
        return False
    subject = str(ed.get("subject") or "Welcome to Chugh Vibes")
    plain = str(ed.get("plain") or "")
    body_html = str(ed.get("html") or "")
    if not body_html:
        return False
    return _acs_send(to, subject, plain, body_html)

@app.route(route="f", methods=["GET"], auth_level=func.AuthLevel.ANONYMOUS)
def feedback(req: func.HttpRequest) -> func.HttpResponse:
    token = (req.params.get("t") or "").strip()
    if not token:
        return func.HttpResponse("Missing token.", status_code=400)

    try:
        tokens = _tables().get_table_client("feedbacktokens")
        entity = tokens.get_entity(partition_key="tok", row_key=token)
    except ResourceNotFoundError:
        return func.HttpResponse("This feedback link is not valid.", status_code=404)
    except Exception:
        logging.exception("feedback: token lookup failed")
        return func.HttpResponse("Temporary error, please try again.", status_code=503)

    action = str(entity.get("action", ""))
    if action not in _ACTIONS:
        return func.HttpResponse("Unknown action.", status_code=400)
    item_id = str(entity.get("itemId", ""))
    lens = str(entity.get("lens", ""))
    if not lens:
        return func.HttpResponse("This feedback link is not valid.", status_code=404)
    row_key, value = _ACTIONS[action]

    try:
        events = _tables().get_table_client("feedbackevents")
        events.upsert_entity(
            {
                "PartitionKey": item_id,
                "RowKey": f"{lens}:{row_key}",
                "lens": lens,
                "value": value,
                "action": action,
                "ts": int(time.time()),
            },
            mode=UpdateMode.REPLACE,
        )
    except Exception:
        logging.exception("feedback: event write failed")
        return func.HttpResponse("Temporary error, please try again.", status_code=503)

    if action == "click":
        url = str(entity.get("url", ""))
        if url.startswith(("http://", "https://")):
            return func.HttpResponse(status_code=302, headers={"Location": url})
        return _page("Thanks — noted.")

    messages = {"up": "Thanks — more like this 👍", "down": "Got it — less like this 👎",
                "save": "Saved to learn from ⭐"}
    return _page(messages.get(action, "Thanks — noted."))


@app.route(route="subscribe", methods=["POST"], auth_level=func.AuthLevel.ANONYMOUS)
def subscribe(req: func.HttpRequest) -> func.HttpResponse:
    try:
        data = req.get_json()
    except ValueError:
        return _json(400, False, "Invalid request.")

    email = str(data.get("email", "")).strip().lower()
    name = str(data.get("name", "")).strip()[:80]
    trap = str(data.get("company", "")).strip()
    # honeypot: real users never fill the hidden field — pretend success, store nothing
    if trap:
        return _json(200, True, "Almost there — check your inbox to confirm.")
    if not _EMAIL_RE.match(email) or len(email) > 254:
        return _json(400, False, "That email doesn't look right.")

    key = _email_key(email)
    now = int(time.time())
    try:
        table = _subscribers()
        try:
            active = table.get_entity("sub", key)
            if str(active.get("status")) == "active":
                return _json(200, True, "You're already on the list.")
        except ResourceNotFoundError:
            pass
        try:
            pend = table.get_entity("pending", key)
            if now - int(pend.get("createdTs", 0)) < _RESEND_WINDOW:
                return _json(200, True, "Almost there — check your inbox to confirm.")
            token = str(pend.get("token") or secrets.token_urlsafe(24))
            user_id = str(pend.get("userId") or _new_user_id())
        except ResourceNotFoundError:
            token = secrets.token_urlsafe(24)
            user_id = _new_user_id()
        table.upsert_entity(
            {
                "PartitionKey": "pending", "RowKey": key,
                "email": email, "name": name, "token": token, "userId": user_id,
                "createdTs": now, "status": "pending",
            },
            mode=UpdateMode.REPLACE,
        )
    except Exception:
        logging.exception("subscribe: store failed")
        return _json(503, False, "Temporary error, please try again.")

    _send_confirmation(email, name, f"{_api_base(req)}/confirm?t={token}")
    return _json(200, True, "Almost there — check your inbox to confirm.")


@app.route(route="confirm", methods=["GET"], auth_level=func.AuthLevel.ANONYMOUS)
def confirm(req: func.HttpRequest) -> func.HttpResponse:
    token = (req.params.get("t") or "").strip()
    if not token:
        return _page("This confirmation link is missing its token.", ok=False)
    try:
        table = _subscribers()
        rows = list(table.query_entities(
            "PartitionKey eq 'pending' and token eq @tok",
            parameters={"tok": token},
        ))
    except Exception:
        logging.exception("confirm: lookup failed")
        return _page("Temporary error, please try again.", ok=False)

    if not rows:
        # Idempotent: a second click on an already-confirmed link is friendly, not an error.
        try:
            done = list(table.query_entities(
                "PartitionKey eq 'sub' and token eq @tok",
                parameters={"tok": token},
            ))
        except Exception:
            done = []
        if done:
            return _page("You're already confirmed — you're on the list.", ok=True)
        return _page("This link is invalid or already used.", ok=False)

    ent = rows[0]
    key = str(ent["RowKey"])
    email = str(ent.get("email", ""))
    name = str(ent.get("name", ""))
    user_id = str(ent.get("userId") or _new_user_id())
    try:
        table.upsert_entity(
            {
                "PartitionKey": "sub", "RowKey": key,
                "email": email, "name": name, "token": token, "userId": user_id,
                "status": "active", "confirmedTs": int(time.time()),
            },
            mode=UpdateMode.REPLACE,
        )
        table.delete_entity("pending", key)
    except Exception:
        logging.exception("confirm: activate failed")
        return _page("Temporary error, please try again.", ok=False)

    # Trigger this new user's first edition right away (graceful if no cache yet).
    if _send_welcome(email):
        return _page("You're in. Your first edition is on its way to your inbox.", ok=True)
    return _page("You're in. Your first edition lands tomorrow morning.", ok=True)
