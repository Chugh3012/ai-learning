from __future__ import annotations

import hashlib
import html
import json
import logging
import os
import re
import secrets
import time
from datetime import datetime, timezone
from urllib.parse import urlencode, parse_qs

import azure.functions as func
from azure.core.exceptions import ResourceExistsError, ResourceNotFoundError
from azure.data.tables import TableServiceClient, UpdateMode
from azure.identity import DefaultAzureCredential

app = func.FunctionApp()

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_SUBSCRIBERS = "subscribers"
_RESEND_WINDOW = 600  # don't re-send a confirmation to the same address within 10 min
_CONFIRM_TTL = 48 * 3600  # a confirmation link is good for 48 hours
_FEEDBACK_TTL = 90 * 24 * 3600  # a feedback link is good for 90 days
_RATE_WINDOW = 3600  # per-IP sliding window for subscribe abuse guard
_RATE_LIMIT = 10  # max confirmation sends a single IP can trigger per window
_GLOBAL_LIMIT = 60  # absolute cap on confirmation sends per window (spoof-proof backstop)

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

def _html_page(title: str, body_inner: str, ok: bool = True) -> func.HttpResponse:
    accent = "#2438e0" if ok else "#6b6357"
    body = (
        '<!doctype html><html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        f'<title>{html.escape(title)}</title>'
        '<link rel="preconnect" href="https://fonts.googleapis.com">'
        '<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>'
        '<link href="https://fonts.googleapis.com/css2?family=Fraunces:opsz,wght@9..144,500;9..144,600&family=Inter:wght@400;500;600&display=swap" rel="stylesheet">'
        '</head><body style="margin:0;background:#f3efe4;color:#1a1712;'
        "font-family:Inter,system-ui,sans-serif;min-height:100vh;display:flex;"
        'align-items:center;justify-content:center">'
        '<main style="width:min(92vw,34rem);padding:2rem">'
        f'<p style="font-family:Fraunces,Georgia,serif;font-size:1.05rem;margin:0 0 1.25rem">'
        f'chugh<span style="color:{accent}">·</span>vibes</p>'
        f'{body_inner}'
        '</main></body></html>'
    )
    return func.HttpResponse(body, mimetype="text/html", status_code=200)

def _json(status: int, ok: bool, message: str) -> func.HttpResponse:
    return func.HttpResponse(
        json.dumps({"ok": ok, "message": message}),
        status_code=status, mimetype="application/json",
    )

def _email_key(email: str) -> str:
    return hashlib.sha256(email.encode("utf-8")).hexdigest()

def _strip_port(value: str) -> str:
    v = (value or "").strip()
    if not v:
        return ""
    if v.startswith("["):  # [ipv6]:port
        return v[1:v.index("]")] if "]" in v else v
    if v.count(":") == 1:  # ipv4:port
        return v.split(":")[0]
    return v  # bare ipv4, or ipv6 without a port

def _client_ip(req: func.HttpRequest) -> str:
    # Use a platform-observed IP, NOT a client-forgeable header. X-Azure-SocketIP is the raw
    # TCP peer (not client-settable); failing that, Azure App Service appends the real client
    # IP as the LAST X-Forwarded-For hop, so the last entry — not the first — is trustworthy.
    sock = req.headers.get("X-Azure-SocketIP", "").strip()
    if sock:
        return _strip_port(sock)
    fwd = req.headers.get("X-Forwarded-For", "")
    if fwd:
        return _strip_port(fwd.split(",")[-1])
    return _strip_port(req.headers.get("X-Azure-ClientIP", "")) or "unknown"

def _under_cap(table, part: str, key: str, limit: int, now: int) -> bool:
    try:
        row = table.get_entity(part, key)
        start = int(row.get("windowStart", 0))
        count = int(row.get("count", 0))
    except ResourceNotFoundError:
        start, count = now, 0
    if now - start >= _RATE_WINDOW:
        start, count = now, 0
    if count >= limit:
        return False
    table.upsert_entity(
        {"PartitionKey": part, "RowKey": key, "windowStart": start, "count": count + 1},
        mode=UpdateMode.REPLACE,
    )
    return True

def _rate_ok(req: func.HttpRequest) -> bool:
    # Two layered fixed-window caps on confirmation sends: per trusted-IP (stops one source)
    # AND a global cap (bounds total email volume even if the source IP is spoofed/rotated).
    # Fail-open: if the counter store is unreachable we still serve (availability first).
    ip = _client_ip(req)
    ipkey = hashlib.sha256(ip.encode("utf-8")).hexdigest()
    now = int(time.time())
    try:
        svc = _tables()
        try:
            svc.create_table_if_not_exists("ratelimit")
        except Exception:
            pass
        table = svc.get_table_client("ratelimit")
        if not _under_cap(table, "ip", ipkey, _RATE_LIMIT, now):
            logging.warning("subscribe_rate_limited: per-IP cap hit")
            return False
        if not _under_cap(table, "global", "confirm", _GLOBAL_LIMIT, now):
            logging.warning("subscribe_rate_limited: global confirmation cap hit")
            return False
        return True
    except Exception:
        logging.exception("subscribe_rate_limit_store_failed: allowing")
        return True

def _new_user_id() -> str:
    return "usr_" + secrets.token_hex(4)

def _subscribers():
    svc = _tables()
    try:
        svc.create_table_if_not_exists(_SUBSCRIBERS)
    except Exception:
        pass
    return svc.get_table_client(_SUBSCRIBERS)

def _profiles():
    svc = _tables()
    try:
        svc.create_table_if_not_exists("profiles")
    except Exception:
        pass
    return svc.get_table_client("profiles")

def _ensure_default_profile(user_id: str) -> None:
    # Give a newly-confirmed subscriber their own profile row (one user -> many profiles).
    # No-op if they already have profiles (e.g. admin/builder seeded with curated feeds).
    if not user_id:
        return
    try:
        profs = _profiles()
        existing = list(profs.query_entities("PartitionKey eq @uid", parameters={"uid": user_id}))
        if existing:
            return
        profs.upsert_entity({
            "PartitionKey": user_id, "RowKey": "prf_daily",
            "name": "Daily edition", "channel": "email", "cadence": "daily",
            "top": 5, "min_score": 55, "interest": "", "self_review": False,
        }, mode=UpdateMode.REPLACE)
    except Exception:
        logging.exception("confirm: default profile create failed")

def _api_base(req: func.HttpRequest) -> str:
    override = os.environ.get("SUBSCRIBE_API_BASE", "")
    if override:
        return override.rstrip("/")
    from urllib.parse import urlsplit
    parts = urlsplit(req.url)
    return f"https://{parts.netloc}/api"

def _active_subscriber(token: str) -> dict | None:
    rows = list(_subscribers().query_entities(
        "PartitionKey eq 'sub' and token eq @tok",
        parameters={"tok": token},
    ))
    for row in rows:
        if str(row.get("status", "")) == "active":
            return dict(row)
    return None

def _profile_for_user(user_id: str, profile_id: str = "") -> dict | None:
    if not user_id:
        return None
    table = _profiles()
    rows = list(table.query_entities("PartitionKey eq @uid", parameters={"uid": user_id}))
    if not rows:
        _ensure_default_profile(user_id)
        rows = list(table.query_entities("PartitionKey eq @uid", parameters={"uid": user_id}))
    if not rows:
        return None
    if profile_id:
        return next((dict(r) for r in rows if str(r.get("RowKey", "")) == profile_id), None)
    return dict(next((r for r in rows if str(r.get("RowKey", "")) == "prf_daily"), rows[0]))

def _request_fields(req: func.HttpRequest) -> dict:
    try:
        data = req.get_json()
        if isinstance(data, dict):
            return data
    except ValueError:
        pass
    body = req.get_body().decode("utf-8", "replace") if hasattr(req, "get_body") else ""
    parsed = parse_qs(body, keep_blank_values=True)
    return {k: v[-1] if v else "" for k, v in parsed.items()}

def _int_between(value, default: int, low: int, high: int) -> int:
    try:
        n = int(value)
    except (TypeError, ValueError):
        n = default
    return max(low, min(high, n))

def _float_between(value, default: float, low: float, high: float) -> float:
    try:
        n = float(value)
    except (TypeError, ValueError):
        n = default
    return max(low, min(high, n))

def _preference_update(raw: dict, current: dict) -> dict:
    cadence = str(raw.get("cadence") or current.get("cadence") or "daily").strip().lower()
    if cadence not in {"daily", "weekly"}:
        cadence = "daily"
    return {
        "cadence": cadence,
        "top": _int_between(raw.get("top"), int(current.get("top", 5)), 1, 10),
        "min_score": _float_between(raw.get("min_score"), float(current.get("min_score", 55)), 0, 100),
        "interest": str(raw.get("interest", current.get("interest", ""))).strip()[:500],
    }

def _preferences_page(token: str, profile: dict, saved: bool = False) -> func.HttpResponse:
    pid = str(profile.get("RowKey", ""))
    action = f"/api/preferences?{urlencode({'t': token, 'p': pid})}"
    cadence = str(profile.get("cadence", "daily")).lower()
    top = html.escape(str(profile.get("top", 5)), quote=True)
    min_score = html.escape(str(profile.get("min_score", 55)), quote=True)
    interest = html.escape(str(profile.get("interest", "")))
    daily = " selected" if cadence == "daily" else ""
    weekly = " selected" if cadence == "weekly" else ""
    note = ('<p style="background:#e8f0ff;color:#18267a;padding:.75rem 1rem;'
            'border-radius:4px;margin:0 0 1rem">Preferences saved.</p>') if saved else ""
    body = (
        '<h1 style="font-family:Fraunces,Georgia,serif;font-weight:500;'
        'font-size:2rem;margin:0 0 .5rem">Tune your edition</h1>'
        '<p style="color:#6b6357;line-height:1.5;margin:0 0 1.5rem">'
        'Adjust what your next Chugh Vibes brief optimizes for.</p>'
        f'{note}'
        f'<form method="post" action="{html.escape(action, quote=True)}" '
        'style="display:grid;gap:1rem">'
        '<label style="display:grid;gap:.35rem;font-weight:600">Cadence'
        '<select name="cadence" style="font:inherit;padding:.75rem;border:1px solid #cfc7b8;'
        f'background:white"><option value="daily"{daily}>Daily</option>'
        f'<option value="weekly"{weekly}>Weekly</option></select></label>'
        '<label style="display:grid;gap:.35rem;font-weight:600">Edition size'
        f'<input name="top" type="number" min="1" max="10" value="{top}" '
        'style="font:inherit;padding:.75rem;border:1px solid #cfc7b8"></label>'
        '<label style="display:grid;gap:.35rem;font-weight:600">Quality floor'
        f'<input name="min_score" type="number" min="0" max="100" step="1" value="{min_score}" '
        'style="font:inherit;padding:.75rem;border:1px solid #cfc7b8"></label>'
        '<label style="display:grid;gap:.35rem;font-weight:600">Interests'
        f'<textarea name="interest" rows="5" maxlength="500" '
        'style="font:inherit;padding:.75rem;border:1px solid #cfc7b8;resize:vertical">'
        f'{interest}</textarea></label>'
        '<button type="submit" style="font:inherit;font-weight:600;background:#2438e0;color:white;'
        'border:0;padding:.9rem 1rem;border-radius:2px">Save preferences</button>'
        '</form>'
    )
    return _html_page("Chugh Vibes preferences", body)

def _saved_page(items: list[dict]) -> func.HttpResponse:
    if not items:
        body = (
            '<h1 style="font-family:Fraunces,Georgia,serif;font-weight:500;'
            'font-size:2rem;margin:0 0 .5rem">Saved library</h1>'
            '<p style="color:#6b6357;line-height:1.5;margin:0">'
            'Saved items will collect here after you tap save in an edition.</p>'
        )
        return _html_page("Chugh Vibes saved library", body)
    rows = []
    for item in items:
        title = html.escape(str(item.get("title") or f"Saved item {item.get('PartitionKey', '')}"))
        url = str(item.get("url") or "")
        try:
            ts = datetime.fromtimestamp(int(item.get("ts")), tz=timezone.utc).strftime("%b %d, %Y")
        except (TypeError, ValueError):
            ts = ""
        if url.startswith(("http://", "https://")):
            safe_url = html.escape(url, quote=True)
            title_html = f'<a href="{safe_url}" style="color:#2438e0;text-decoration:none">{title}</a>'
        else:
            title_html = title
        rows.append(
            '<li style="padding:1rem 0;border-top:1px solid #d8d0c1">'
            f'<div style="font-weight:600;line-height:1.4">{title_html}</div>'
            f'<div style="color:#6b6357;font-size:.85rem;margin-top:.35rem">{ts}</div>'
            '</li>'
        )
    body = (
        '<h1 style="font-family:Fraunces,Georgia,serif;font-weight:500;'
        'font-size:2rem;margin:0 0 .5rem">Saved library</h1>'
        '<p style="color:#6b6357;line-height:1.5;margin:0 0 1.5rem">'
        'Your saved Chugh Vibes items, newest first.</p>'
        f'<ol style="list-style:none;margin:0;padding:0">{"".join(rows)}</ol>'
    )
    return _html_page("Chugh Vibes saved library", body)

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

def _acs_send(to: str, subject: str, plain: str, body_html: str,
              headers: dict[str, str] | None = None) -> bool:
    endpoint = os.environ.get("ACS_ENDPOINT", "")
    sender = os.environ.get("EMAIL_SENDER", "")
    if not (endpoint and sender):
        logging.warning("email: ACS not configured; not sent")
        return False
    try:
        from azure.communication.email import EmailClient
        client = EmailClient(endpoint, DefaultAzureCredential())
        message = {
            "senderAddress": sender,
            "recipients": {"to": [{"address": to}]},
            "content": {"subject": subject, "plainText": plain, "html": body_html},
        }
        if headers:
            message["headers"] = headers
        client.begin_send(message).result()
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

def _send_welcome(to: str, unsubscribe_url: str = "", preference_url: str = "") -> bool:
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
    headers = None
    footer_links: list[str] = []
    if preference_url:
        safe_pref = html.escape(preference_url, quote=True)
        plain += f"\n\nPreferences: {preference_url}\n"
        footer_links.append(f'<a href="{safe_pref}" style="color:#999">preferences</a>')
    if unsubscribe_url:
        safe = html.escape(unsubscribe_url, quote=True)
        plain += f"\n\nUnsubscribe: {unsubscribe_url}\n"
        footer_links.append(f'<a href="{safe}" style="color:#999">unsubscribe</a>')
        headers = {
            "List-Unsubscribe": f"<{unsubscribe_url}>",
            "List-Unsubscribe-Post": "List-Unsubscribe=One-Click",
        }
    if footer_links:
        body_html += (
            '<p style="color:#999;font-size:12px;font-family:Inter,Arial,sans-serif">'
            + ' &middot; '.join(footer_links) + '</p>')
    return _acs_send(to, subject, plain, body_html, headers)

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
    expires = int(entity.get("expiresTs") or (int(entity.get("ts", 0)) + _FEEDBACK_TTL))
    if time.time() > expires:
        logging.info("feedback_expired: token past TTL")
        return func.HttpResponse("This feedback link has expired.", status_code=410)
    item_id = str(entity.get("itemId", ""))
    lens = str(entity.get("lens", ""))
    if not lens:
        return func.HttpResponse("This feedback link is not valid.", status_code=404)
    row_key, value = _ACTIONS[action]
    url = str(entity.get("url", ""))
    title = str(entity.get("title", ""))

    try:
        events = _tables().get_table_client("feedbackevents")
        events.upsert_entity(
            {
                "PartitionKey": item_id,
                "RowKey": f"{lens}:{row_key}",
                "lens": lens,
                "value": value,
                "action": action,
                "title": title,
                "url": url,
                "ts": int(time.time()),
            },
            mode=UpdateMode.REPLACE,
        )
    except Exception:
        logging.exception("feedback: event write failed")
        return func.HttpResponse("Temporary error, please try again.", status_code=503)

    if action == "click":
        if url.startswith(("http://", "https://")):
            return func.HttpResponse(status_code=302, headers={"Location": url})
        return _page("Thanks — noted.")

    messages = {"up": "Thanks — more like this 👍", "down": "Got it — less like this 👎",
                "save": "Saved to learn from ⭐"}
    return _page(messages.get(action, "Thanks — noted."))

@app.route(route="preferences", methods=["GET", "POST"], auth_level=func.AuthLevel.ANONYMOUS)
def preferences(req: func.HttpRequest) -> func.HttpResponse:
    token = (req.params.get("t") or "").strip()
    if not token:
        return _page("This preference link is missing its token.", ok=False)
    try:
        sub = _active_subscriber(token)
    except Exception:
        logging.exception("preferences: subscriber lookup failed")
        return _page("Temporary error, please try again.", ok=False)
    if not sub:
        return _page("This preference link is invalid or inactive.", ok=False)

    user_id = str(sub.get("userId", ""))
    profile_id = str(req.params.get("p") or "")
    try:
        profile = _profile_for_user(user_id, profile_id)
    except Exception:
        logging.exception("preferences: profile lookup failed")
        return _page("Temporary error, please try again.", ok=False)
    if not profile:
        return _page("This edition profile could not be found.", ok=False)

    if req.method == "POST":
        update = _preference_update(_request_fields(req), profile)
        profile.update(update)
        try:
            _profiles().update_entity(
                {
                    "PartitionKey": user_id,
                    "RowKey": str(profile["RowKey"]),
                    **update,
                    "updatedTs": int(time.time()),
                },
                mode=UpdateMode.MERGE,
            )
            logging.info("preferences_saved")
        except Exception:
            logging.exception("preferences: update failed")
            return _page("Temporary error, please try again.", ok=False)
        return _preferences_page(token, profile, saved=True)

    return _preferences_page(token, profile)

@app.route(route="saved", methods=["GET"], auth_level=func.AuthLevel.ANONYMOUS)
def saved(req: func.HttpRequest) -> func.HttpResponse:
    token = (req.params.get("t") or "").strip()
    if not token:
        return _page("This saved-library link is missing its token.", ok=False)
    try:
        sub = _active_subscriber(token)
    except Exception:
        logging.exception("saved: subscriber lookup failed")
        return _page("Temporary error, please try again.", ok=False)
    if not sub:
        return _page("This saved-library link is invalid or inactive.", ok=False)

    user_id = str(sub.get("userId", ""))
    profile_id = str(req.params.get("p") or "")
    try:
        profile = _profile_for_user(user_id, profile_id)
    except Exception:
        logging.exception("saved: profile lookup failed")
        return _page("Temporary error, please try again.", ok=False)
    if not profile:
        return _page("This edition profile could not be found.", ok=False)

    lens = f"{user_id}:{profile['RowKey']}"
    try:
        events = _tables().get_table_client("feedbackevents")
        # ponytail: cross-partition scan of feedbackevents (no PartitionKey filter). Fine at
        # one-user/low-volume scale; if saves grow, mirror saves into a per-user saved table.
        rows = list(events.query_entities(
            "lens eq @lens and action eq 'save'",
            parameters={"lens": lens},
        ))
    except Exception:
        logging.exception("saved: event lookup failed")
        return _page("Temporary error, please try again.", ok=False)
    rows.sort(key=lambda r: int(r.get("ts", 0) or 0), reverse=True)
    return _saved_page(rows)


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
        if not _rate_ok(req):
            return _json(429, False, "Too many requests. Please try again in a little while.")
        table.upsert_entity(
            {
                "PartitionKey": "pending", "RowKey": key,
                "email": email, "name": name, "token": token, "userId": user_id,
                "kind": "subscriber",
                "createdTs": now, "status": "pending",
            },
            mode=UpdateMode.REPLACE,
        )
    except Exception:
        logging.exception("subscribe: store failed")
        return _json(503, False, "Temporary error, please try again.")

    if _send_confirmation(email, name, f"{_api_base(req)}/confirm?t={token}"):
        logging.info("subscribe_confirmation_sent")
    else:
        logging.warning("subscribe_confirmation_send_failed")
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
    if int(time.time()) - int(ent.get("createdTs", 0)) > _CONFIRM_TTL:
        try:
            table.delete_entity("pending", key)
        except Exception:
            pass
        return _page("This confirmation link has expired. Please subscribe again.", ok=False)
    email = str(ent.get("email", ""))
    name = str(ent.get("name", ""))
    user_id = str(ent.get("userId") or _new_user_id())
    kind = str(ent.get("kind") or "subscriber")
    try:
        table.upsert_entity(
            {
                "PartitionKey": "sub", "RowKey": key,
                "email": email, "name": name, "token": token, "userId": user_id,
                "kind": kind,
                "status": "active", "confirmedTs": int(time.time()),
            },
            mode=UpdateMode.REPLACE,
        )
        table.delete_entity("pending", key)
    except Exception:
        logging.exception("confirm: activate failed")
        return _page("Temporary error, please try again.", ok=False)

    _ensure_default_profile(user_id)

    # Trigger this new user's first edition right away (graceful if no cache yet).
    base = _api_base(req)
    unsubscribe_url = f"{base}/unsubscribe?t={token}"
    preference_url = f"{base}/preferences?{urlencode({'t': token, 'p': 'prf_daily'})}"
    if _send_welcome(email, unsubscribe_url, preference_url):
        return _page("You're in. Your first edition is on its way to your inbox.", ok=True)
    return _page("You're in. Your first edition lands tomorrow morning.", ok=True)


@app.route(route="unsubscribe", methods=["GET", "POST"], auth_level=func.AuthLevel.ANONYMOUS)
def unsubscribe(req: func.HttpRequest) -> func.HttpResponse:
    # One-click unsubscribe. GET = footer link (returns a page); POST = RFC 8058
    # List-Unsubscribe-Post (mail clients call it silently, expect 200). Idempotent.
    token = (req.params.get("t") or "").strip()
    if not token:
        return _page("This unsubscribe link is missing its token.", ok=False)
    try:
        table = _subscribers()
        rows = list(table.query_entities(
            "PartitionKey eq 'sub' and token eq @tok",
            parameters={"tok": token},
        ))
    except Exception:
        logging.exception("unsubscribe: lookup failed")
        if req.method == "POST":
            return func.HttpResponse(status_code=202)
        return _page("Temporary error, please try again.", ok=False)

    for ent in rows:
        try:
            table.update_entity(
                {
                    "PartitionKey": "sub", "RowKey": str(ent["RowKey"]),
                    "status": "unsubscribed", "unsubscribedTs": int(time.time()),
                },
                mode=UpdateMode.MERGE,
            )
            logging.info("unsubscribe_success")
        except Exception:
            logging.exception("unsubscribe: update failed")

    if req.method == "POST":
        return func.HttpResponse(status_code=200)
    return _page("You're unsubscribed. You won't get any more editions.", ok=True)
