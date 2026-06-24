from __future__ import annotations

from moviepy import TextClip

from reelforge.domain.style import Style

def _chunks(text: str, n: int) -> list[str]:
    words = text.split()
    return [" ".join(words[i:i + n]) for i in range(0, len(words), n)] or [""]

def caption_clips(text: str, seconds: float, style: Style,
                  starts: list[tuple[str, float, float]] | None = None) -> list[TextClip]:
    """Word/phrase-synced captions — the #1 'this is a reel' signal. Big, bold, centered, a few
    words flashing at a time. `starts` (chunk, start, dur) overrides the timing when a voiceover
    provides word boundaries (a later checkpoint); otherwise chunks are spread evenly across the
    scene."""
    if starts is None:
        chunks = [c for c in _chunks(text, style.words_per_chunk) if c]
        if not chunks:
            return []
        span = seconds / len(chunks)
        starts = [(c, i * span, span) for i, c in enumerate(chunks)]

    box_w = style.width - 160
    box_h = int(style.height * 0.30)   # a fixed caption zone so chunks don't jump vertically
    # Shrink the font so the single longest word still fits the box. Anton is a condensed face,
    # so caps run ~0.46x the font size; prevents long words overflowing the frame.
    longest = max((len(w) for w in text.split()), default=1)
    size = max(40, min(style.caption_size, int(box_w / (0.46 * longest))))
    y_top = int(style.caption_y * style.height - box_h / 2)
    out: list[TextClip] = []
    for chunk, start, dur in starts:
        if not chunk.strip():
            continue
        out.append(
            TextClip(text=chunk.upper(), font=style.font_path, font_size=size,
                     color=style.caption_color, stroke_color=style.caption_stroke,
                     stroke_width=style.caption_stroke_width, method="caption",
                     size=(box_w, box_h), text_align="center", horizontal_align="center",
                     vertical_align="center")
            .with_position(("center", y_top)).with_start(start).with_duration(dur))
    return out
