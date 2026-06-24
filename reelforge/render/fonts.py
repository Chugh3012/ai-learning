from __future__ import annotations

from pathlib import Path

_ASSETS = Path(__file__).resolve().parent.parent / "assets" / "fonts"
# Anton (OFL) — a heavy condensed display face bundled for a consistent reel look on every machine
# (local + CI), so rendering never depends on system fonts.
_BUNDLED = _ASSETS / "Anton-Regular.ttf"

_FALLBACKS = (
    "C:/Windows/Fonts/arialbd.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/dejavu/DejaVuSans-Bold.ttf",
)

def resolve_font(preferred: str = "") -> str | None:
    if preferred and Path(preferred).exists():
        return preferred
    if _BUNDLED.exists():
        return str(_BUNDLED)
    for path in _FALLBACKS:
        if Path(path).exists():
            return path
    return None
