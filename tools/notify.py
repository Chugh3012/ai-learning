#!/usr/bin/env python3
"""Per-user delivery, called by kb_sync. From the one shared ranking, picks each user's top-N
— shared relevance + their interest match (two-tower) + their feedback affinity, above their
min_score — curates, and sends via their channel: 'email' (Azure Communication Services) or
'digest' (a dated markdown file). Per-user state is namespaced in signal.kind (sent:<id>,
affinity:<id>). Feedback links work on every channel and degrade gracefully when feedback infra
is unconfigured. Passwordless throughout.
"""
from __future__ import annotations

import html
import json
import random
import re
import secrets
import sqlite3
import time

_ACTIONS = ("up", "down", "save", "click")


def _interest_weight() -> float:
    """How strongly a user's interest match steers their pick (config/feedback.json).
    0 = off (pure shared relevance + feedback). Read once per delivery run."""
    from pathlib import Path
    cfg = Path(__file__).resolve().parent.parent / "config" / "feedback.json"
    try:
        return float(json.loads(cfg.read_text(encoding="utf-8")).get("interest_weight", 0))
    except Exception:  # noqa: BLE001
        return 0.0


def _explore_ratio() -> float:
    """Fraction of each user's top-N reserved for EXPLORATION (config/feedback.json). 0 = pure
    exploit (always the highest-scored). e.g. 0.2 on a top-5 = 1 wildcard slot. Read per run."""
    from pathlib import Path
    cfg = Path(__file__).resolve().parent.parent / "config" / "feedback.json"
    try:
        return float(json.loads(cfg.read_text(encoding="utf-8")).get("explore_ratio", 0.0))
    except Exception:  # noqa: BLE001
        return 0.0


def _weighted_sample(items: list[dict], k: int, rng: random.Random) -> list[dict]:
    """Pick k items WITHOUT replacement, weighted by score — exploration still favors decent
    items but is genuinely stochastic (a softmax-ish nudge, not pure random)."""
    pool = list(items)
    weights = [max(float(d.get("score", 0)), 1.0) for d in pool]
    out: list[dict] = []
    for _ in range(min(k, len(pool))):
        i = rng.choices(range(len(pool)), weights=weights, k=1)[0]
        out.append(pool.pop(i))
        weights.pop(i)
    return out


def _explore_exploit(items: list[dict], top: int, ratio: float,
                     rng: random.Random | None = None) -> list[dict]:
    """Balance EXPLOIT (highest final_score) with EXPLORE (a stochastic pick from the other
    quality-gated candidates). Reserves round(top*ratio) of the top-N for score-weighted samples
    drawn from BELOW the exploit cut — keeping the filter bubble from closing and gathering
    feedback on under-seen items. `items` must be pre-sorted best-first and already gated/deduped/
    diversified. ratio<=0 or too few spare items -> pure exploit. Returns up to `top`, score-sorted."""
    rng = rng or random
    if ratio <= 0 or len(items) <= top:
        return items[:top]
    n_explore = min(max(1, round(top * ratio)), top - 1, len(items) - top)
    if n_explore <= 0:
        return items[:top]
    n_exploit = top - n_explore
    exploit = items[:n_exploit]
    explore = _weighted_sample(items[n_exploit:], n_explore, rng)
    chosen = exploit + explore
    chosen.sort(key=lambda d: d["score"], reverse=True)
    return chosen


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


def _lessons(endpoint: str, deployment: str, items: list[tuple]) -> tuple[str, dict[int, dict]]:
    """Turn the day's picks into a LEARNING BRIEF in one batched Foundry call. Returns
    (theme, cards) where `theme` is a one-line throughline over the whole set and each card is
    {lesson, try, what}: the takeaway, a concrete 30-second experiment to try (or ""), and one
    line of context. Grounded in the best available text; never invents. Degrades to {} on any
    failure (caller falls back to titles)."""
    if not endpoint:
        return "", {}
    try:
        from foundry import openai_client
        client = openai_client(endpoint)
    except Exception as e:  # noqa: BLE001
        print(f"email: lesson client failed ({e}); sending titles only")
        return "", {}
    listing = "\n\n".join(
        f"[{i}] {t}\n{_clean(s)}" if _clean(s) else f"[{i}] {t}"
        for i, t, s in items
    )
    system = (
        "You are the editor of a daily LEARNING brief for a reader who wants to use AI/LLMs "
        "better. Turn the items into cards that TEACH, not summaries.\n"
        "First write THEME: one short line (<=14 words) naming the throughline across today's "
        "items — the pattern a curious reader should notice (no hype, only what the items show).\n"
        "Then for EACH item write a card with two fields:\n"
        "  lesson: 1-2 sentences — the concrete takeaway/technique/insight to apply or understand "
        "(lead with the 'how'/'so what'; for a personal account, surface the craft — the prompt, "
        "instruction, or workflow choice — as the lesson). Self-contained: the reader should get "
        "the point without needing a separate description.\n"
        "  try: ONE imperative line a reader could actually do in ~30 seconds to feel the idea "
        "(a prompt to test, a setting to flip, a question to ask the model). Empty string if the "
        "item genuinely has nothing to try (news/release).\n"
        "Be concrete, non-hyped, grounded in the provided text; never invent specifics. Return "
        "ONLY JSON: {\"theme\":\"<line>\",\"cards\":[{\"id\":<int>,\"lesson\":\"..\",\"try\":\"..\"}, "
        "...]} for every id."
    )
    try:
        resp = client.chat.completions.create(
            model=deployment,
            messages=[{"role": "system", "content": system},
                      {"role": "user", "content": listing}],
            temperature=0.3,
            response_format={"type": "json_object"},
            max_tokens=1800,
        )
        from foundry import log_usage
        log_usage("email", resp)
        data = json.loads(resp.choices[0].message.content)
        cards = {int(c["id"]): {"lesson": str(c.get("lesson", "")).strip(),
                                "try": str(c.get("try", "")).strip(),
                                "what": str(c.get("what", "")).strip()}
                 for c in data.get("cards", [])}
        return str(data.get("theme", "")).strip(), cards
    except Exception as e:  # noqa: BLE001
        print(f"email: lesson generation failed ({e}); sending titles only")
        return "", {}


def _connections(con: sqlite3.Connection, user_id: str,
                 selected: list[dict], min_cos: float = 0.62) -> dict[int, tuple[str, str]]:
    """Connect-the-dots: link each of today's picks to the most similar item this user was
    ALREADY sent (the owned, embedded history nobody else has). Returns {item_id: (past_title,
    past_url)} for pairs whose cosine >= min_cos. Pure-stdlib over the embedding table; no model
    call. Best-effort: returns {} if embeddings/history are unavailable."""
    try:
        from embed import unpack, dot
    except Exception:  # noqa: BLE001
        return {}
    today_ids = [d["id"] for d in selected]
    if not today_ids:
        return {}
    # Vectors for today's picks.
    today_vecs: dict[int, list[float]] = {}
    for iid in today_ids:
        row = con.execute("SELECT vec FROM embedding WHERE item_id=?", (iid,)).fetchone()
        if row and row[0]:
            today_vecs[iid] = unpack(row[0])
    if not today_vecs:
        return {}
    # Past items this user was sent, that have an embedding (exclude today's picks).
    past = con.execute(
        "SELECT e.item_id, i.title, i.url, e.vec FROM embedding e "
        "JOIN item i ON i.id=e.item_id "
        "JOIN signal s ON s.item_id=e.item_id AND s.kind=? ",
        (f"sent:{user_id}",),
    ).fetchall()
    today_set = set(today_ids)
    past = [(pid, t, u, v) for pid, t, u, v in past if pid not in today_set and v]
    if not past:
        return {}
    # Score every (today, past) pair, then assign greedily strongest-first so each PAST item is
    # referenced at most ONCE across the digest (no repeated 'Related to ...' lines).
    pairs = []
    for iid, tvec in today_vecs.items():
        for pid, title, url, pvec in past:
            c = dot(tvec, unpack(pvec))
            if c >= min_cos:
                pairs.append((c, iid, pid, title, url))
    pairs.sort(reverse=True)
    out: dict[int, tuple[str, str]] = {}
    used_today: set[int] = set()
    used_past: set[int] = set()
    for _c, iid, pid, title, url in pairs:
        if iid in used_today or pid in used_past:
            continue
        out[iid] = (title, url)
        used_today.add(iid)
        used_past.add(pid)
    return out


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


def _render(items: list[tuple], theme: str, cards: dict[int, dict],
            connections: dict[int, tuple[str, str]] | None = None,
            feedback_url: str = "", tokens: dict[int, dict[str, str]] | None = None,
            ) -> tuple[str, str]:
    """Return (plain_text, html) for a LEARNING BRIEF: a one-line throughline header, then a
    card per item (💡 lesson · 🔧 try this · ↪ related past pick), with 👍/👎/save + source links.
    Both renderings degrade gracefully when fields are empty."""
    tokens = tokens or {}
    connections = connections or {}
    fb = bool(feedback_url and tokens)

    def link(item_id: int, action: str) -> str:
        return f"{feedback_url}?t={tokens[item_id][action]}"

    text_lines: list[str] = []
    html_lines = [
        '<div style="font-family:system-ui,Segoe UI,Arial,sans-serif;max-width:640px">',
        '<h2 style="margin:0 0 4px">ai-scout \u2014 today\u2019s learning brief</h2>',
    ]
    if theme:
        text_lines.append(f"Today's throughline: {theme}\n")
        html_lines.append(
            f'<p style="color:#0a66c2;font-size:14px;font-weight:600;margin:0 0 16px">'
            f'\u2728 {html.escape(theme)}</p>')
    else:
        html_lines.append('<p style="color:#666;margin:0 0 16px">New ways to use AI, ranked for you.</p>')

    for idx, (item_id, title, url) in enumerate(items, 1):
        card = cards.get(item_id) or {}
        lesson = card.get("lesson", "")
        try_it = card.get("try", "")
        conn = connections.get(item_id)
        src = link(item_id, "click") if fb else url

        # ---- plain text (also the digest channel) ----
        text_lines.append(f"{idx}. {title}")
        if lesson:
            text_lines.append(f"   \U0001f4a1 {lesson}")
        if try_it:
            text_lines.append(f"   \U0001f527 Try: {try_it}")
        if conn:
            text_lines.append(f"   \u21aa Related: {conn[0]}")
        text_lines.append(f"   {url}")
        if fb:
            text_lines.append(
                f"   feedback: 👍 {link(item_id, 'up')}  |  👎 {link(item_id, 'down')}  "
                f"|  ⭐ {link(item_id, 'save')}")
        text_lines.append("")

        # ---- html card ----
        row = [
            '<div style="margin:0 0 22px;padding:0 0 16px;border-bottom:1px solid #ececec">',
            '<div style="font-weight:600;font-size:16px;color:#111;line-height:1.35">'
            f'<span style="color:#0a66c2">{idx}.</span> {html.escape(title)}</div>',
        ]
        if lesson:
            row.append('<div style="color:#333;font-size:14px;line-height:1.55;margin:8px 0">'
                       f'\U0001f4a1 {html.escape(lesson)}</div>')
        if try_it:
            row.append('<div style="background:#eef4ff;border-left:3px solid #0a66c2;'
                       'padding:8px 12px;margin:8px 0;font-size:13px;color:#0a3d6e;border-radius:3px">'
                       f'\U0001f527 <b>Try:</b> {html.escape(try_it)}</div>')
        row.append(
            '<div style="margin:8px 0 0;font-size:13px">'
            f'<a href="{html.escape(src)}" style="color:#0a66c2;text-decoration:none;font-weight:600">'
            'Read the source \u2192</a></div>')
        if conn:
            row.append('<div style="color:#999;font-size:12px;margin:6px 0 0">'
                       f'\u21aa Related to an earlier pick: {html.escape(conn[0])}</div>')
        if fb:
            row.append(
                '<div style="margin-top:10px;font-size:13px">'
                f'<a href="{html.escape(link(item_id, "up"))}" style="text-decoration:none;margin-right:16px">👍 more</a>'
                f'<a href="{html.escape(link(item_id, "down"))}" style="text-decoration:none;margin-right:16px">👎 less</a>'
                f'<a href="{html.escape(link(item_id, "save"))}" style="text-decoration:none">⭐ save</a>'
                '</div>')
        row.append('</div>')
        html_lines.append("".join(row))

    html_lines.append('<p style="color:#999;font-size:12px">ai-scout \u00b7 daily learning brief</p></div>')
    return "\n".join(text_lines), "\n".join(html_lines)


def _select_for_user(con: sqlite3.Connection, user_id: str, top: int,
                     min_score: float = 0.0, interest_vec: list[float] | None = None,
                     interest_weight: float = 0.0) -> list[dict]:
    """Per-user pick, two-stage (the standard recsys design):
      1. RETRIEVAL (SQL): candidate items this user hasn't been sent that carry a relevance
         score (the shared quality gate), capped — with their affinity and embedding.
      2. RANKING (Python): final = relevance + this user's affinity + interest match bonus
         (z-scored cosine to the user's interest vector). Gate by min_score, then curate.
    The interest bonus is what lets e.g. a research paper on better prompting SURFACE for a
    user whose interest matches it — without hand-filtering sources. With no interest vector
    (or no embeddings yet) the bonus is 0 and this is exactly the old relevance+affinity pick.
    State is namespaced per user in signal.kind: sent:<id>, affinity:<id>."""
    sent_kind = f"sent:{user_id}"
    aff_kind = f"affinity:{user_id}"
    rows = con.execute(
        "SELECT i.id, i.title, i.url, i.summary, i.source_id, "
        "  (SELECT t.topic FROM tag t WHERE t.item_id=i.id LIMIT 1) AS topic, "
        "  s.value AS rel, "
        "  COALESCE((SELECT a.value FROM signal a WHERE a.item_id=i.id AND a.kind=?), 0) AS aff, "
        "  (SELECT e.vec FROM embedding e WHERE e.item_id=i.id) AS vec, "
        "  (SELECT src.category FROM source src WHERE src.id=i.source_id) AS category "
        "FROM item i "
        "JOIN signal s ON s.item_id=i.id AND s.kind='relevance' "
        "WHERE NOT EXISTS (SELECT 1 FROM signal e WHERE e.item_id=i.id AND e.kind=?) "
        "GROUP BY i.id "
        "ORDER BY (s.value + aff) DESC, i.published DESC LIMIT ?",
        (aff_kind, sent_kind, max(top * 20, 200)),
    ).fetchall()
    if not rows:
        return []

    from embed import match_bonus
    vecs = {r[0]: r[8] for r in rows if r[8]}
    bonus = match_bonus(interest_vec, vecs, interest_weight)

    pool = []
    for iid, title, url, summary, source_id, topic, rel, aff, _vec, category in rows:
        score = rel + aff + bonus.get(iid, 0.0)
        if score >= min_score:
            pool.append({"id": iid, "title": title, "url": url, "summary": summary,
                         "source_id": source_id, "topic": topic, "category": category,
                         "score": score})
    pool.sort(key=lambda d: d["score"], reverse=True)

    # Cross-delivery dedup: never resend a story already shown to this user, even from a different
    # source/item id (sent:<user> only blocks the exact item). Compare titles to past deliveries.
    seen_titles = [r[0] for r in con.execute(
        "SELECT i.title FROM item i JOIN signal s ON s.item_id=i.id AND s.kind=?", (sent_kind,)
    ).fetchall()]

    from curate import dedup, diversify, drop_seen
    # Quality-gate -> dedup -> drop already-seen, then diversify to a WINDOW larger than top so
    # exploration has genuine alternatives to sample from; finally balance exploit vs explore.
    gated = drop_seen(dedup(pool), seen_titles)
    window = diversify(gated, max(top * 3, top + 6))
    return _explore_exploit(window, top, _explore_ratio())


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


def _deliver_digest(user_id: str, count: int, plain: str, item_ids: list[int] | None = None) -> bool:
    """The agent's channel: write the picks to a dated digest file the next coding session
    reads. No long-term memory — the file IS the rolling window; old ones can be deleted.
    Embeds a machine-readable item-id footer so the outcome-as-feedback loop (P13) can map a
    merged/closed PR back to the radar items and record 👍/👎 automatically."""
    from pathlib import Path
    from datetime import datetime, timezone
    out_dir = Path(__file__).resolve().parent.parent / "digests"
    out_dir.mkdir(exist_ok=True)
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    out = out_dir / f"{user_id}-{today}.md"
    header = (f"# ai-scout \u2014 {user_id} digest \u2014 {today}\n\n"
              f"_{count} items from the shared ranking, reordered by {user_id}'s feedback. "
              f"Read, act if useful (the commit is the record), then ignore next cycle._\n\n")
    footer = f"\n\n<!-- items: {','.join(str(i) for i in (item_ids or []))} -->\n"
    out.write_text(header + plain + footer, encoding="utf-8")
    print(f"deliver: wrote {out.relative_to(out_dir.parent)}")
    return True


def deliver_all(con: sqlite3.Connection, users: list[dict], env: dict,
                foundry_endpoint: str, model: str) -> int:
    """Deliver each user's personalized top-N from the ONE shared ranking, via their channel.
    Shared machinery (ingest/KB/ranking) is untouched; only per-user state differs. Each user
    is delivered DAILY but only items clearing their min_score quality bar — a quiet day sends
    nothing. Feedback links (👍/👎/save) work on EVERY channel, so all users (including the agent
    on the digest channel) personalize through the same Function. Returns total items delivered."""
    acs_endpoint = env.get("ACS_ENDPOINT", "")
    sender = env.get("EMAIL_SENDER", "")
    feedback_url = env.get("FEEDBACK_URL", "")
    feedback_account = env.get("FEEDBACK_STORAGE", "")
    embed_model = env.get("FOUNDRY_EMBED_NAME", "embed")
    interest_weight = _interest_weight()
    total = 0
    for user in users:
        uid = user["id"]
        channel = user.get("channel", "email")
        top = int(user.get("top", 5))
        min_score = float(user.get("min_score", 0))
        # User tower: embed this user's interest sentence once (None -> no interest steering).
        from embed import embed_interest
        interest_vec = embed_interest(foundry_endpoint, embed_model, user.get("interest", ""))
        selected = _select_for_user(con, uid, top, min_score, interest_vec, interest_weight)
        if not selected:
            print(f"deliver: nothing clears {uid}'s bar (min_score={min_score:g}) — quiet day")
            continue

        rows = [(d["id"], d["title"], d["url"]) for d in selected]
        blurb_items = [(d["id"], d["title"], _fulltext(d["url"]) or d["summary"]) for d in selected]
        theme, cards = _lessons(foundry_endpoint, model, blurb_items)
        connections = _connections(con, uid, selected)
        # Feedback links are unified across channels: mint per-user tokens whenever feedback is
        # configured, regardless of email vs digest. The agent clicks them just like a human.
        tokens = _mint_tokens(feedback_account, uid, rows) if feedback_url else {}
        plain, body_html = _render(rows, theme, cards, connections, feedback_url, tokens)

        if channel == "email":
            to = env.get(user.get("email_var", "EMAIL_TO"), "")
            ok = _deliver_email(acs_endpoint, sender, to, len(rows), plain, body_html)
        else:
            ok = _deliver_digest(uid, len(rows), plain, [r[0] for r in rows])

        if ok:
            _mark_sent(con, uid, [r[0] for r in rows])
            total += len(rows)
            print(f"deliver: sent {len(rows)} to {uid} ({channel})")
    return total
