from __future__ import annotations

from pathlib import Path

_MUSIC = Path(__file__).resolve().parent.parent / "assets" / "music" / "ambient.mp3"

def bundled_music() -> str:
    """Path to the bundled ambient bed (synthesized, CC0). Empty if missing."""
    return str(_MUSIC) if _MUSIC.exists() else ""
