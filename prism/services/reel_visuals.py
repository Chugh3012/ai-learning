from __future__ import annotations

import random

from reelforge import FallbackVisuals, PexelsVisuals, SoraVisuals

def make_visuals(settings, creative: dict, ai_visuals: bool, *, dry_run: bool = False,
                 rng: random.Random | None = None):
    """Pick the b-roll provider for a render from config (config/reel.json `visuals` + the
    `ai_visuals` feature flag), with graceful fallbacks. Returns a Visual provider or None (None =>
    the compositor uses the branded gradient). When AI visuals are on, Sora leads with Pexels as a
    safety net, so a failed / over-budget / dry-run generation still yields footage."""
    pexels = PexelsVisuals(api_key=settings.pexels_api_key, rng=rng) if settings.pexels_api_key else None

    mode = "sora" if ai_visuals else creative.get("visuals", "pexels")
    if mode != "sora":
        return pexels

    cfg = creative.get("sora") if isinstance(creative.get("sora"), dict) else {}
    sora = SoraVisuals(
        endpoint=settings.foundry_project_endpoint,
        deployment=settings.foundry_sora_deployment or cfg.get("deployment", "sora"),
        size=cfg.get("size", "720x1280"),
        max_seconds=float(cfg.get("max_seconds", 0) or 0),
        max_clip_seconds=int(cfg.get("max_clip_seconds", 12)),
        price_per_second=float(cfg.get("price_per_second", 0.10)),
        dry_run=dry_run,
    )
    return FallbackVisuals([sora, pexels])
