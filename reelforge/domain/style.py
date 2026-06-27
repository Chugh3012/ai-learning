from __future__ import annotations

from pydantic import BaseModel

RGB = tuple[int, int, int]

def hexrgb(c: RGB) -> str:
    return "#{:02x}{:02x}{:02x}".format(*c)

class Style(BaseModel):
    """The look of a reel: canvas, palette, caption typography, motion. Themeable — a template is
    just a Style preset. Captions are the star, so most knobs are about them."""

    width: int = 1080
    height: int = 1920
    fps: int = 30

    # palette (RGB)
    bg_top: RGB = (22, 28, 96)        # deep cobalt
    bg_bottom: RGB = (8, 8, 16)       # near-ink
    accent: RGB = (150, 176, 255)     # bright cobalt (kicker / highlight)
    caption_color: str = "white"
    caption_active: str = "#ffe14d"   # karaoke highlight color for the currently-spoken word
    caption_stroke: str = "#0a0a12"
    caption_stroke_width: int = 8

    font_path: str = ""               # resolved at render time when empty
    caption_size: int = 104
    kicker_size: int = 44
    kicker_stroke_width: int = 4      # heavier stroke keeps the kicker legible over bright b-roll
    words_per_chunk: int = 3          # how many words flash on screen at once
    caption_y: float = 0.5            # vertical anchor (0=top, 1=bottom)
    caption_pop: float = 0.18         # scale-bounce of the spoken word as it lights up (0 = none)

    kenburns: float = 0.14            # background zoom over a scene (more motion = more momentum)
    grade: bool = True                # unify b-roll with one cinematic color grade so it feels like one film
    vignette: float = 0.20            # edge darkening on b-roll (0 = none) — focuses the eye, premium look
    scrim: float = 0.42               # dark overlay opacity over b-roll, so captions stay legible
    bitrate: str = "10000k"           # high-quality H.264 target for crisp 1080x1920 upload
    music_volume: float = 0.26        # music bed level under the voiceover (0 = silent)
    sfx: bool = True                  # sound design: a riser under the hook + a soft whoosh at each cut
