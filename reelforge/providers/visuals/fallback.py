from __future__ import annotations

class FallbackVisuals:
    """Try each visual provider in order and return the first non-None background clip — so an AI
    provider (Sora) can lead with a stock provider (Pexels) as a safety net, while the branded
    gradient stays the final fallback inside the compositor. Implements the Visual protocol; closes
    every wrapped provider."""

    def __init__(self, providers: list):
        self.providers = [p for p in providers if p is not None]

    def background(self, query, seconds, style, tmp, prompt=""):
        for p in self.providers:
            clip = p.background(query, seconds, style, tmp, prompt=prompt)
            if clip is not None:
                return clip
        return None

    def close(self) -> None:
        for p in self.providers:
            try:
                p.close()
            except Exception:
                pass
