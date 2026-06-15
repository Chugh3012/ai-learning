#!/usr/bin/env python3
"""ai-scout email delivery (Layer F / P6) — pluggable, called by kb_sync.

Sends a daily email of the top relevance-ranked items the user hasn't been emailed yet:
each = a one-line "why it matters" (Foundry nano) + title + link to the source. No quiz.

Passwordless throughout: Azure Communication Services Email via DefaultAzureCredential
(az login locally, OIDC managed identity in CI), and Foundry for the blurbs. No keys.

Incremental: items already emailed are marked in the KB `signal` table (kind='emailed'),
so each item is sent once. Cost-capped by --email-top. Graceful: if ACS isn't configured
the stage is skipped and the pipeline continues.

Feedback note: feedback capture (👍/👎, save, click) is a planned next step; when its
endpoint exists, per-item links drop into the HTML here. We don't ship dead buttons.
"""
from __future__ import annotations

import html
import json
import sqlite3
import time


def _blurbs(endpoint: str, deployment: str, items: list[tuple]) -> dict[int, str]:
    """One-line 'why it matters' per item, in a single batched Foundry call."""
    if not endpoint:
        return {}
    try:
        from foundry import openai_client
        client = openai_client(endpoint)
    except Exception as e:  # noqa: BLE001
        print(f"email: blurb client failed ({e}); sending titles only")
        return {}
    listing = "\n".join(f"{i}: {t}" for i, t, _u in items)
    system = (
        "For each item, write ONE concise sentence (<=22 words) on why it matters for someone "
        "learning new ways to USE AI/LLMs. Practical, non-hyped. Return ONLY JSON: "
        '{"blurbs":[{"id":<int>,"s":"<sentence>"}, ...]} for every id.'
    )
    try:
        resp = client.chat.completions.create(
            model=deployment,
            messages=[{"role": "system", "content": system},
                      {"role": "user", "content": listing}],
            temperature=0.3,
            response_format={"type": "json_object"},
            max_tokens=500,
        )
        data = json.loads(resp.choices[0].message.content)
        return {int(b["id"]): str(b["s"]) for b in data.get("blurbs", [])}
    except Exception as e:  # noqa: BLE001
        print(f"email: blurb generation failed ({e}); sending titles only")
        return {}


def _render(items: list[tuple], blurbs: dict[int, str]) -> tuple[str, str]:
    """Return (plain_text, html) for the email body."""
    text_lines, html_lines = [], [
        '<div style="font-family:system-ui,Segoe UI,Arial,sans-serif;max-width:640px">',
        '<h2 style="margin:0 0 4px">ai-scout \u2014 today\u2019s top picks</h2>',
        '<p style="color:#666;margin:0 0 16px">New ways to use AI, ranked for you.</p>',
    ]
    for idx, (item_id, title, url) in enumerate(items, 1):
        blurb = blurbs.get(item_id, "")
        text_lines.append(f"{idx}. {title}\n   {blurb}\n   {url}\n")
        html_lines.append(
            f'<div style="margin:0 0 18px;padding:0 0 14px;border-bottom:1px solid #eee">'
            f'<div style="font-weight:600;font-size:15px">{html.escape(title)}</div>'
            f'<div style="color:#444;font-size:14px;margin:4px 0 6px">{html.escape(blurb)}</div>'
            f'<a href="{html.escape(url)}" style="color:#0a66c2;font-size:13px">Read the source \u2192</a>'
            f'</div>'
        )
    html_lines.append('<p style="color:#999;font-size:12px">ai-scout \u00b7 daily digest</p></div>')
    return "\n".join(text_lines), "\n".join(html_lines)


def send_email(con: sqlite3.Connection, acs_endpoint: str, sender: str, to: str,
               foundry_endpoint: str, model: str, top: int) -> int:
    """Email the top-N not-yet-emailed ranked items. Returns count sent (0 if skipped)."""
    if not (acs_endpoint and sender and to):
        return 0
    rows = con.execute(
        "SELECT i.id, i.title, i.url FROM item i "
        "JOIN signal s ON s.item_id=i.id AND s.kind='relevance' "
        "WHERE NOT EXISTS (SELECT 1 FROM signal e WHERE e.item_id=i.id AND e.kind='emailed') "
        "ORDER BY s.value DESC, i.published DESC LIMIT ?",
        (top,),
    ).fetchall()
    if not rows:
        print("email: nothing new to send")
        return 0

    blurbs = _blurbs(foundry_endpoint, model, rows)
    plain, body_html = _render(rows, blurbs)

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
