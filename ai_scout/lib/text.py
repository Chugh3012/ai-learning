from __future__ import annotations

import html
import re

def clean(text: str, limit: int = 900) -> str:
    text = re.sub(r"<[^>]+>", " ", text or "")
    text = html.unescape(text)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:limit]

def fulltext(url: str, limit: int = 2500) -> str:
    if not url:
        return ""
    try:
        import trafilatura
        downloaded = trafilatura.fetch_url(url)
        if not downloaded:
            return ""
        text = trafilatura.extract(downloaded, include_comments=False, include_tables=False)
        return clean(text or "", limit)
    except Exception:
        return ""
