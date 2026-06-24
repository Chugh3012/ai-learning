from __future__ import annotations

import numpy as np
from moviepy import ImageClip

from reelforge.domain.style import Style

def gradient_bg(seconds: float, style: Style) -> ImageClip:
    """A branded vertical gradient with subtle grain, slowly zoomed (Ken Burns) so the frame is
    never static. Oversized by the zoom amount; the compositor crops to frame by centering it."""
    h, w = style.height, style.width
    top = np.array(style.bg_top, dtype=float)
    bottom = np.array(style.bg_bottom, dtype=float)
    ramp = np.linspace(0.0, 1.0, h)[:, None]                 # h x 1
    grad = top[None, :] * (1.0 - ramp) + bottom[None, :] * ramp   # h x 3
    arr = np.repeat(grad[:, None, :], w, axis=1)             # h x w x 3
    grain = np.random.default_rng(7).integers(-6, 7, (h, w, 1))
    arr = np.clip(arr + grain, 0, 255).astype("uint8")
    clip = ImageClip(arr).with_duration(seconds)
    z = style.kenburns
    return clip.resized(lambda t: 1.0 + z * (t / max(seconds, 0.1)))
