#!/usr/bin/env python3
"""ai-scout delivery (Layer F / P6+P11) — multi-user, pluggable, called by kb_sync.

Delivers each user's personalized top-N from the ONE shared relevance ranking, via that
user's channel (config/users.json). A user is just {id, channel, top}: ingest, KB, and the
single ranking are SHARED; only per-user state differs, namespaced in signal.kind:
  sent:<id>      — items already delivered to this user (so each is sent once)
  affinity:<id>  — this user's learned +/- feedback bias (NewsBlur-style additive)
Adding a user = one entry in users.json. No per-user prompt; personalization is feedback only.

Channels: 'email' (Azure Communication Services, with 👍/👎/save feedback links) and 'digest'
(a dated markdown file under digests/, used by the agent maintaining this app — user 2).

Each item = a short multi-sentence crux (Foundry, grounded in fetched article text or the
feed summary) + title + source link. Passwordless throughout (DefaultAzureCredential).

Feedback (P7): when a feedback endpoint + token store are configured (FEEDBACK_URL +
FEEDBACK_STORAGE), each emailed item carries 👍/👎/save buttons and a click-tracked source link.
Each gesture is an opaque, single-purpose token minted here and stored in the
`feedbacktokens` table; the Function validates it and records an event. If feedback infra
isn't configured the email degrades gracefully to a plain source link (no dead buttons).
"""
from __future__ import annotations

import html
import json
import re
import secrets
import sqlite3
import time

_ACTIONS = ("up", "down", "save", "click")


def _clean(text: str, limit: int = 900) -> str:
    """Strip HTML tags/entities from a feed summary so the model sees clean prose."""
    text = re.sub(r"<[^>]+>", " ", text or "")
    text = html.unescape(text)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:limit]


def _fulltext(url: str, limit: int = 2500) -> str:
    """Best-effort fetch of the article body for a deeper crux. Returns '' on any failure
    (paywall, JS page, timeout, dep missing) so the caller falls back to the feed summary."""
    if not url:
        return ""
    try:
        import trafilatura
        downloaded = trafilatura.fetch_url(url)
        if not downloaded:
            return ""
        text = trafilatura.extract(downloaded, include_comments=False, include_tables=False)
        return _clean(text or "", limit)
    except Exception:  # noqa: BLE001 — enrichment is optional, never break the email
        return ""


def _blurbs(endpoint: str, deployment: str, items: list[tuple]) -> dict[int, str]:
    """A short multi-sentence crux per item (the gist of the article + why it matters),
    grounded in the best available text (fetched article body, else feed summary), in a
    single batched Foundry call."""
    if not endpoint:
        return {}
    try:
        from foundry import openai_client
        client = openai_client(endpoint)
    except Exception as e:  # noqa: BLE001
        print(f"email: blurb client failed ({e}); sending titles only")
        return {}
    listing = "\n\n".join(
        f"[{i}] {t}\n{_clean(s)}" if _clean(s) else f"[{i}] {t}"
        for i, t, s in items
    )
    system = (
        "You summarize tech/AI articles for a busy reader who wants the core crux up front and "
        "will click through only if it's worth it. For each item write 2-4 sentences (about 45-75 "
        "words) capturing what it actually says — the key idea, what's new, and why it matters for "
        "someone learning new ways to USE AI/LLMs. Be concrete and non-hyped; ground it in the "
        "provided text and never invent specifics. Return ONLY JSON: "
        '{"blurbs":[{"id":<int>,"s":"<summary>"}, ...]} for every id.'
    )
    try:
        resp = client.chat.completions.create(
            model=deployment,
            messages=[{"role": "system", "content": system},
                      {"role": "user", "content": listing}],
            temperature=0.3,
            response_format={"type": "json_object"},
            max_tokens=1300,
        )
        from foundry import log_usage
        log_usage("email", resp)
        data = json.loads(resp.choices[0].message.content)
        return {int(b["id"]): str(b["s"]) for b in data.get("blurbs", [])}
    except Exception as e:  # noqa: BLE001
        print(f"email: blurb generation failed ({e}); sending titles only")
        return {}


def _mint_tokens(account: str, user_id: str, items: list[tuple]) -> dict[int, dict[str, str]]:
    """Mint an opaque token per (user, item, action) and store it in the `feedbacktokens`
    table. Returns {item_id: {action: token}}. Returns {} (graceful) if the store is down."""
    if not account:
        return {}
    try:
        from azure.data.tables import TableServiceClient, UpdateMode
        from azure.identity import DefaultAzureCredential
        table = TableServiceClient(
            endpoint=f"https://{account}.table.core.windows.net",
            credential=DefaultAzureCredential(),
        ).get_table_client("feedbacktokens")
    except Exception as e:  # noqa: BLE001
        print(f"deliver: feedback tokens unavailable ({e}); sending plain links")
        return {}

    out: dict[int, dict[str, str]] = {}
    try:
        for item_id, _title, url in items:
            per: dict[str, str] = {}
            for action in _ACTIONS:
                tok = secrets.token_urlsafe(16)
                table.upsert_entity(
                    {"PartitionKey": "tok", "RowKey": tok, "user": user_id,
                     "itemId": int(item_id), "action": action, "url": url,
                     "ts": int(time.time())},
                    mode=UpdateMode.REPLACE,
                )
                per[action] = tok
            out[item_id] = per
    except Exception as e:  # noqa: BLE001
        print(f"deliver: token minting failed ({e}); sending plain links")
        return {}
    return out


def _render(items: list[tuple], blurbs: dict[int, str],
            feedback_url: str = "", tokens: dict[int, dict[str, str]] | None = None) -> tuple[str, str]:
    """Return (plain_text, html) for the email body. If feedback_url + tokens are present,
    render 👍/👎/save buttons and a click-tracked source link; else a plain source link."""
    tokens = tokens or {}
    fb = bool(feedback_url and tokens)

    def link(item_id: int, action: str) -> str:
        return f"{feedback_url}?t={tokens[item_id][action]}"

    text_lines, html_lines = [], [
        '<div style="font-family:system-ui,Segoe UI,Arial,sans-serif;max-width:640px">',
        '<h2 style="margin:0 0 4px">ai-scout \u2014 today\u2019s top picks</h2>',
        '<p style="color:#666;margin:0 0 16px">New ways to use AI, ranked for you.</p>',
    ]
    for idx, (item_id, title, url) in enumerate(items, 1):
        blurb = blurbs.get(item_id, "")
        src = link(item_id, "click") if fb else url
        text_lines.append(f"{idx}. {title}\n   {blurb}\n   {url}\n")
        row = [
            f'<div style="margin:0 0 18px;padding:0 0 14px;border-bottom:1px solid #eee">',
            f'<div style="font-weight:600;font-size:15px">{html.escape(title)}</div>',
            f'<div style="color:#444;font-size:14px;line-height:1.5;margin:6px 0 8px">{html.escape(blurb)}</div>',
            f'<a href="{html.escape(src)}" style="color:#0a66c2;font-size:13px">Read the source \u2192</a>',
        ]
        if fb:
            row.append(
                '<div style="margin-top:8px;font-size:13px">'
                f'<a href="{html.escape(link(item_id, "up"))}" style="text-decoration:none;margin-right:14px">👍 more</a>'
                f'<a href="{html.escape(link(item_id, "down"))}" style="text-decoration:none;margin-right:14px">👎 less</a>'
                f'<a href="{html.escape(link(item_id, "save"))}" style="text-decoration:none">⭐ save</a>'
                '</div>'
            )
        row.append('</div>')
        html_lines.append("".join(row))
    html_lines.append('<p style="color:#999;font-size:12px">ai-scout \u00b7 daily digest</p></div>')
    return "\n".join(text_lines), "\n".join(html_lines)


def _select_for_user(con: sqlite3.Connection, user_id: str, top: int) -> list[dict]:
    """Per-user pick: top items from the SHARED relevance ranking that this user hasn't been
    sent yet, reordered by THIS user's own feedback affinity. Then curate (dedup + diversity).
    State is namespaced per user in signal.kind: sent:<id>, affinity:<id>."""
    sent_kind = f"sent:{user_id}"
    aff_kind = f"affinity:{user_id}"
    candidates = con.execute(
        "SELECT i.id, i.title, i.url, i.summary, i.source_id, "
        "  (SELECT t.topic FROM tag t WHERE t.item_id=i.id LIMIT 1) AS topic "
        "FROM item i "
        "JOIN signal s ON s.item_id=i.id AND s.kind='relevance' "
        "WHERE NOT EXISTS (SELECT 1 FROM signal e WHERE e.item_id=i.id AND e.kind=?) "
        "ORDER BY (s.value + COALESCE("
        "  (SELECT a.value FROM signal a WHERE a.item_id=i.id AND a.kind=?), 0)) DESC, "
        "i.published DESC LIMIT ?",
        (sent_kind, aff_kind, max(top * 6, 30)),
    ).fetchall()
    from curate import dedup, diversify
    pool = [{"id": r[0], "title": r[1], "url": r[2], "summary": r[3],
             "source_id": r[4], "topic": r[5]} for r in candidates]
    return diversify(dedup(pool), top)


def _mark_sent(con: sqlite3.Connection, user_id: str, item_ids: list[int]) -> None:
    now = int(time.time())
    con.executemany(
        "INSERT INTO signal(item_id,kind,value,ts) VALUES(?,?,?,?)",
        [(i, f"sent:{user_id}", 1.0, now) for i in item_ids],
    )
    con.commit()


def _deliver_email(acs_endpoint: str, sender: str, to: str, count: int,
                   plain: str, body_html: str) -> bool:
    if not (acs_endpoint and sender and to):
        print(f"deliver: email channel not configured for recipient; skipped")
        return False
    try:
        from azure.communication.email import EmailClient
        from azure.identity import DefaultAzureCredential
        client = EmailClient(acs_endpoint, DefaultAzureCredential())
        client.begin_send({
            "senderAddress": sender,
            "recipients": {"to": [{"address": to}]},
            "content": {"subject": f"ai-scout \u2014 {count} new ways to use AI",
                        "plainText": plain, "html": body_html},
        }).result()
        return True
    except Exception as e:  # noqa: BLE001 — optional stage, never break the pipeline
        print(f"deliver: email send failed ({e})")
        return False


def _deliver_digest(user_id: str, count: int, plain: str) -> bool:
    """The agent's channel: write the picks to a dated digest file the next coding session
    reads. No long-term memory — the file IS the rolling window; old ones can be deleted."""
    from pathlib import Path
    from datetime import datetime, timezone
    out_dir = Path(__file__).resolve().parent.parent / "digests"
    out_dir.mkdir(exist_ok=True)
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    out = out_dir / f"{user_id}-{today}.md"
    header = (f"# ai-scout \u2014 {user_id} digest \u2014 {today}\n\n"
              f"_{count} items from the shared ranking, reordered by {user_id}'s feedback. "
              f"Read, act if useful (the commit is the record), then ignore next cycle._\n\n")
    out.write_text(header + plain, encoding="utf-8")
    print(f"deliver: wrote {out.relative_to(out_dir.parent)}")
    return True


def deliver_all(con: sqlite3.Connection, users: list[dict], env: dict,
                foundry_endpoint: str, model: str) -> int:
    """Deliver each user's personalized top-N from the ONE shared ranking, via their channel.
    Shared machinery (ingest/KB/ranking) is untouched; only per-user state differs. Returns
    total items delivered across users."""
    acs_endpoint = env.get("ACS_ENDPOINT", "")
    sender = env.get("EMAIL_SENDER", "")
    feedback_url = env.get("FEEDBACK_URL", "")
    feedback_account = env.get("FEEDBACK_STORAGE", "")
    total = 0
    for user in users:
        uid = user["id"]
        channel = user.get("channel", "email")
        top = int(user.get("top", 5))
        selected = _select_for_user(con, uid, top)
        if not selected:
            print(f"deliver: nothing new for {uid}")
            continue

        rows = [(d["id"], d["title"], d["url"]) for d in selected]
        blurb_items = [(d["id"], d["title"], _fulltext(d["url"]) or d["summary"]) for d in selected]
        blurbs = _blurbs(foundry_endpoint, model, blurb_items)
        # Email gets clickable feedback links; the digest channel uses plain text (no clicks).
        tokens = _mint_tokens(feedback_account, uid, rows) if (channel == "email" and feedback_url) else {}
        plain, body_html = _render(rows, blurbs, feedback_url, tokens)

        if channel == "email":
            to = env.get(user.get("email_var", "EMAIL_TO"), "")
            ok = _deliver_email(acs_endpoint, sender, to, len(rows), plain, body_html)
        else:
            ok = _deliver_digest(uid, len(rows), plain)

        if ok:
            _mark_sent(con, uid, [r[0] for r in rows])
            total += len(rows)
            print(f"deliver: sent {len(rows)} to {uid} ({channel})")
    return total
