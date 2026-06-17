"""Pure text helpers used by ranking, embedding, and brief rendering — no I/O, no state."""
from __future__ import annotations

import html
import re


def clean(text: str, limit: int = 900) -> str:
    """Strip HTML tags/entities and collapse whitespace so a model/embedder sees clean prose."""
    text = re.sub(r"<[^>]+>", " ", text or "")
    text = html.unescape(text)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:limit]


def fulltext(url: str, limit: int = 2500) -> str:
    """Best-effort fetch of an article body for a deeper crux. Returns '' on any failure
    (paywall, JS page, timeout, missing dep) so the caller falls back to the feed summary."""
    if not url:
        return ""
    try:
        import trafilatura
        downloaded = trafilatura.fetch_url(url)
        if not downloaded:
            return ""
        text = trafilatura.extract(downloaded, include_comments=False, include_tables=False)
        return clean(text or "", limit)
    except Exception:  # noqa: BLE001 — enrichment is optional, never break delivery
        return ""
