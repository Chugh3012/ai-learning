from __future__ import annotations

import numpy as np
from moviepy import AudioArrayClip

# Lightweight synthesized sound design — no external assets. A soft airy WHOOSH accents each cut and
# a RISER builds tension under the hook. Generated with numpy so it ships with the package and stays
# passwordless/offline. Kept subtle (low gain) so it accents the voiceover, never fights it.

_FPS = 44100


def _to_clip(sig: np.ndarray, vol: float) -> AudioArrayClip:
    sig = sig / max(1e-6, float(np.abs(sig).max()))
    a = (sig * vol).astype("float32")
    return AudioArrayClip(np.column_stack([a, a]), fps=_FPS)


def _smooth(x: np.ndarray, k: int) -> np.ndarray:
    # A crude low-pass (moving average) so the noise reads as 'air', not harsh hiss.
    return np.convolve(x, np.ones(k) / k, mode="same")


def whoosh_clip(duration: float = 0.40, vol: float = 0.20) -> AudioArrayClip:
    n = int(_FPS * duration)
    t = np.linspace(0.0, 1.0, n, endpoint=False)
    env = np.sin(np.pi * t) ** 2                       # smooth swell then fade
    noise = _smooth(np.random.default_rng().standard_normal(n), 64)
    return _to_clip(noise * env, vol)


def riser_clip(duration: float = 1.20, vol: float = 0.16) -> AudioArrayClip:
    n = int(_FPS * duration)
    t = np.linspace(0.0, 1.0, n, endpoint=False)
    env = t ** 2                                        # build up toward the cut into the story
    noise = _smooth(np.random.default_rng().standard_normal(n), 48)
    freq = 120.0 + 620.0 * t                            # a rising tone under the noise
    tone = 0.3 * np.sin(2 * np.pi * np.cumsum(freq) / _FPS)
    return _to_clip((noise + tone) * env, vol)
