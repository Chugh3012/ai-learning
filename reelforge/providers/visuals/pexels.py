from __future__ import annotations

import json
import random
import urllib.parse
import urllib.request
from pathlib import Path

from reelforge.providers.visuals.base import cover_crop

_UA = "Mozilla/5.0 reelforge"
_SEARCH = "https://api.pexels.com/videos/search"

class PexelsVisuals:
    """Stock-footage b-roll from Pexels (free API key). Searches portrait video matching a scene's
    query, downloads the best-fit clip, and returns it cover-cropped + muted for the scene length.
    Fully graceful: any failure (no key, no match, network) returns None so render falls back to the
    branded gradient. ponytail: downloads each clip per render (~8MB); add a disk cache if reels get
    frequent."""

    def __init__(self, api_key: str, rng: random.Random | None = None):
        self.api_key = api_key
        self.rng = rng or random.Random()
        self._open: list = []
        self._used: set = set()        # video ids already used this render, so clips don't repeat

    def _search(self, query: str, per_page: int = 15) -> list[dict]:
        qs = urllib.parse.urlencode({"query": query, "orientation": "portrait",
                                     "per_page": per_page, "size": "medium"})
        req = urllib.request.Request(f"{_SEARCH}?{qs}",
                                     headers={"Authorization": self.api_key, "User-Agent": _UA})
        with urllib.request.urlopen(req, timeout=25) as r:
            return json.load(r).get("videos", [])

    @staticmethod
    def _best_file(video: dict, target_w: int) -> dict | None:
        files = [f for f in video.get("video_files", [])
                 if f.get("file_type") == "video/mp4" and (f.get("height") or 0) >= (f.get("width") or 0)]
        files.sort(key=lambda f: abs((f.get("width") or 0) - target_w))
        return files[0] if files else None

    def background(self, query: str, seconds: float, style, tmp: Path, prompt: str = ""):
        # Stock search wants short keywords, so `prompt` (the AI-provider instruction) is ignored.
        from moviepy import VideoFileClip, vfx
        try:
            videos = self._search(query) if self.api_key else []
            if not videos:
                return None
            # Prefer clips we haven't used yet this render so footage doesn't repeat scene-to-scene.
            fresh = [v for v in videos if v.get("id") not in self._used] or videos
            # Pexels returns results in relevance order -- bias to the TOP few so the b-roll actually
            # matches the beat (random over a wide pool was pulling off-topic/blank clips).
            video = self.rng.choice(fresh[: min(3, len(fresh))])
            self._used.add(video.get("id"))
            vf = self._best_file(video, style.width)
            if not vf:
                return None
            dest = Path(tmp) / f"broll_{video.get('id', 'x')}.mp4"
            dreq = urllib.request.Request(vf["link"], headers={"User-Agent": _UA})
            with urllib.request.urlopen(dreq, timeout=60) as r:
                dest.write_bytes(r.read())

            src = VideoFileClip(str(dest)).without_audio()
            self._open.append(src)
            clip = cover_crop(src, style.width, style.height)
            if clip.duration < seconds:
                try:
                    clip = clip.with_effects([vfx.Loop(duration=seconds)])
                except Exception:
                    pass
            else:
                clip = clip.subclipped(0, seconds)
            return clip
        except Exception as e:
            print(f"reel: pexels b-roll failed for {query!r} ({e}); using gradient")
            return None

    def close(self) -> None:
        for clip in self._open:
            try:
                clip.close()
            except Exception:
                pass
        self._open.clear()
