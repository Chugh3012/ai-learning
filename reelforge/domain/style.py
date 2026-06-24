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
    caption_stroke: str = "#0a0a12"
    caption_stroke_width: int = 8

    font_path: str = ""               # resolved at render time when empty
    caption_size: int = 104
    kicker_size: int = 44
    words_per_chunk: int = 3          # how many words flash on screen at once
    caption_y: float = 0.5            # vertical anchor (0=top, 1=bottom)

    kenburns: float = 0.10            # background zoom over a scene
    scrim: float = 0.5                # dark overlay opacity over b-roll, so captions stay legible
