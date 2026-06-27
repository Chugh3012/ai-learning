from __future__ import annotations

import time
from pathlib import Path

from reelforge.providers.visuals.base import cover_crop

# Token scope proven against this account by the embedding path (foundry.embed). The Sora docs show
# https://ai.azure.com/.default for the v1 video API; both work for an AIServices account, so this
# is overridable. ponytail: if a video job 401s, switch token_scope to the ai.azure.com audience.
_SCOPE = "https://cognitiveservices.azure.com/.default"
_ALLOWED = (4, 8, 12)          # Sora 2 discrete clip lengths (the API also supports up to 20s)

class SoraVisuals:
    """AI-generated b-roll from Azure OpenAI Sora 2 (first-party, passwordless via
    DefaultAzureCredential — no keys). Implements the Visual protocol: returns a muted, cover-cropped
    portrait clip for one beat, or None on any failure / when over the per-render second budget, so
    render falls back to the next provider (Pexels) or the branded gradient. Prefers a scene's rich
    `visual_prompt`; falls back to the short b-roll `query`.

    Cost-guarded: `max_seconds` caps total generated seconds per render (0 = unlimited); `dry_run`
    logs each prompt + would-be cost and returns None, so prompts can be reviewed at $0.
    ponytail: generates one clip per beat synchronously (polls the async job). A deep reel is a few
    beats, so this is fine; batch with the queue (two jobs may run at once) if reels get long."""

    def __init__(self, endpoint: str, deployment: str = "sora", *, size: str = "720x1280",
                 max_seconds: float = 0.0, max_clip_seconds: int = 12,
                 price_per_second: float = 0.10, poll_seconds: float = 5.0,
                 token_scope: str = _SCOPE, dry_run: bool = False, credential=None, client=None):
        self.endpoint = endpoint
        self.deployment = deployment
        self.size = size
        self.max_seconds = max_seconds
        self.max_clip_seconds = max_clip_seconds
        self.price_per_second = price_per_second
        self.poll_seconds = poll_seconds
        self.token_scope = token_scope
        self.dry_run = dry_run
        self._credential = credential
        self._client = client
        self._open: list = []
        self.spent_seconds = 0.0

    def _account(self) -> str:
        # The video API lives on the ACCOUNT host (strip the Foundry /api/projects/<name> suffix).
        return self.endpoint.split("/api/projects/", 1)[0].rstrip("/")

    def client(self):
        if self._client is None:
            from azure.identity import DefaultAzureCredential, get_bearer_token_provider
            from openai import OpenAI
            cred = self._credential or DefaultAzureCredential()
            token_provider = get_bearer_token_provider(cred, self.token_scope)
            self._client = OpenAI(base_url=f"{self._account()}/openai/v1/", api_key=token_provider)
        return self._client

    @staticmethod
    def _clip_seconds(seconds: float, cap: int) -> int:
        for d in _ALLOWED:
            if d >= seconds and d <= cap:
                return d
        return min(cap, _ALLOWED[-1])

    def background(self, query: str, seconds: float, style, tmp: Path, prompt: str = ""):
        from moviepy import VideoFileClip, vfx
        # Sora fires ONLY on beats carrying a rich `visual_prompt` (the hero beats); a bare keyword
        # `query` is left to the Pexels fallback. This is what makes the HYBRID mode work.
        text = (prompt or "").strip()
        if not text:
            return None
        clip_s = self._clip_seconds(seconds, self.max_clip_seconds)
        if self.max_seconds and self.spent_seconds + clip_s > self.max_seconds:
            print(f"reel: sora budget reached ({self.max_seconds:g}s); falling back")
            return None
        if self.dry_run:
            print(f"reel: [sora dry-run] {self.size} {clip_s}s ~${clip_s * self.price_per_second:.2f} "
                  f":: {text}")
            return None
        try:
            client = self.client()
            video = client.videos.create(model=self.deployment, prompt=text,
                                         size=self.size, seconds=clip_s)
            while getattr(video, "status", None) not in ("completed", "failed", "cancelled"):
                time.sleep(self.poll_seconds)
                video = client.videos.retrieve(video.id)
            if getattr(video, "status", None) != "completed":
                print(f"reel: sora job {getattr(video, 'status', '?')} for {text[:60]!r}; falling back")
                return None
            self.spent_seconds += clip_s
            dest = Path(tmp) / f"sora_{video.id}.mp4"
            client.videos.download_content(video.id, variant="video").write_to_file(str(dest))

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
            print(f"reel: sora generation failed for {text[:60]!r} ({e}); falling back")
            return None

    def close(self) -> None:
        for clip in self._open:
            try:
                clip.close()
            except Exception:
                pass
        self._open.clear()
