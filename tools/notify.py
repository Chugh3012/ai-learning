#!/usr/bin/env python3
"""ai-scout email delivery (Layer F / P6) — pluggable, called by kb_sync.

Sends a daily email of the top relevance-ranked items the user hasn't been emailed yet:
each = a short multi-sentence crux of the article (Foundry nano, grounded in the feed
summary) + title + link to read the source if it's worth going deeper. No quiz.

Passwordless throughout: Azure Communication Services Email via DefaultAzureCredential
(az login locally, OIDC managed identity in CI), and Foundry for the blurbs. No keys.

Incremental: items already emailed are marked in the KB `signal` table (kind='emailed'),
so each item is sent once. Cost-capped by --email-top. Graceful: if ACS isn't configured
the stage is skipped and the pipeline continues.

Feedback (P7): when a feedback endpoint + token store are configured (FEEDBACK_URL +
FEEDBACK_STORAGE), each item carries 👍/👎/save buttons and a click-tracked source link.
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


def _mint_tokens(account: str, items: list[tuple]) -> dict[int, dict[str, str]]:
    """Mint an opaque token per (item, action) and store it in the `feedbacktokens` table.
    Returns {item_id: {action: token}}. Returns {} (graceful) if the store is unavailable."""
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
        print(f"email: feedback tokens unavailable ({e}); sending plain links")
        return {}

    out: dict[int, dict[str, str]] = {}
    try:
        for item_id, _title, url in items:
            per: dict[str, str] = {}
            for action in _ACTIONS:
                tok = secrets.token_urlsafe(16)
                table.upsert_entity(
                    {"PartitionKey": "tok", "RowKey": tok, "itemId": int(item_id),
                     "action": action, "url": url, "ts": int(time.time())},
                    mode=UpdateMode.REPLACE,
                )
                per[action] = tok
            out[item_id] = per
    except Exception as e:  # noqa: BLE001
        print(f"email: token minting failed ({e}); sending plain links")
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


def send_email(con: sqlite3.Connection, acs_endpoint: str, sender: str, to: str,
               foundry_endpoint: str, model: str, top: int,
               feedback_url: str = "", feedback_account: str = "") -> int:
    """Email the top-N not-yet-emailed ranked items. Returns count sent (0 if skipped).

    Ordering blends LLM relevance with learned feedback affinity (signal kind='affinity',
    written by feedback_ingest) so loved sources/topics rise — NewsBlur-style, additive.
    """
    if not (acs_endpoint and sender and to):
        return 0
    # Pull a larger candidate pool, then curate down: drop near-duplicates and cap how many
    # items any one source/topic contributes, so the top-N feels varied not monotone.
    candidates = con.execute(
        "SELECT i.id, i.title, i.url, i.summary, i.source_id, "
        "  (SELECT t.topic FROM tag t WHERE t.item_id=i.id LIMIT 1) AS topic "
        "FROM item i "
        "JOIN signal s ON s.item_id=i.id AND s.kind='relevance' "
        "WHERE NOT EXISTS (SELECT 1 FROM signal e WHERE e.item_id=i.id AND e.kind='emailed') "
        "ORDER BY (s.value + COALESCE("
        "  (SELECT a.value FROM signal a WHERE a.item_id=i.id AND a.kind='affinity'), 0)) DESC, "
        "i.published DESC LIMIT ?",
        (max(top * 6, 30),),
    ).fetchall()
    if not candidates:
        print("email: nothing new to send")
        return 0

    from curate import dedup, diversify
    pool = [{"id": r[0], "title": r[1], "url": r[2], "summary": r[3],
             "source_id": r[4], "topic": r[5]} for r in candidates]
    selected = diversify(dedup(pool), top)

    rows = [(d["id"], d["title"], d["url"]) for d in selected]            # render/tokens
    # Enrich the crux with the fetched article body when possible; fall back to feed summary.
    blurb_items = [(d["id"], d["title"], _fulltext(d["url"]) or d["summary"]) for d in selected]
    blurbs = _blurbs(foundry_endpoint, model, blurb_items)
    tokens = _mint_tokens(feedback_account, rows) if feedback_url else {}
    plain, body_html = _render(rows, blurbs, feedback_url, tokens)

    try:
        from azure.communication.email import EmailClient
        from azure.identity import DefaultAzureCredential
        client = EmailClient(acs_endpoint, DefaultAzureCredential())
        message = {
            "senderAddress": sender,
            "recipients": {"to": [{"address": to}]},
            "content": {
                "subject": f"ai-scout \u2014 {len(rows)} new ways to use AI",
                "plainText": plain,
                "html": body_html,
            },
        }
        client.begin_send(message).result()
    except Exception as e:  # noqa: BLE001 — optional stage, never break the pipeline
        print(f"email: send failed ({e})")
        return 0

    now = int(time.time())
    con.executemany(
        "INSERT INTO signal(item_id,kind,value,ts) VALUES(?,?,?,?)",
        [(r[0], "emailed", 1.0, now) for r in rows],
    )
    con.commit()
    print(f"email: sent {len(rows)} items to {to}")
    return len(rows)
