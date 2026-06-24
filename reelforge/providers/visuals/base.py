from __future__ import annotations

from pathlib import Path
from typing import Protocol, runtime_checkable

@runtime_checkable
class Visual(Protocol):
    """A b-roll provider: return a muted, full-frame background clip for a scene, or None to let
    the caller fall back to the branded gradient."""

    def background(self, query: str, seconds: float, style, tmp: Path): ...

    def close(self) -> None: ...

def cover_crop(clip, w: int, h: int):
    """Scale a clip to cover w x h, then center-crop — the standard 'fill the frame' for vertical."""
    scale = max(w / clip.w, h / clip.h)
    clip = clip.resized(scale)
    return clip.cropped(x_center=clip.w / 2, y_center=clip.h / 2, width=w, height=h)
