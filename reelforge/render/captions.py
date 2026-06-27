from __future__ import annotations

import re

from moviepy import TextClip

from reelforge.domain.style import Style

def _chunks(text: str, n: int) -> list[str]:
    words = text.split()
    return [" ".join(words[i:i + n]) for i in range(0, len(words), n)] or [""]

def _clean_caption(s: str) -> str:
    # Reel captions read better without stray punctuation: TTS word tokens can leave a leading
    # comma or a floating " ." in a chunk. Drop space-before-punctuation and edge punctuation.
    s = re.sub(r"\s+([,.;:!?])", r"\1", s)
    return s.strip(" \t,.;:!?-–—\"'")

# Function words we avoid ENDING a caption chunk on, so chunks don't dangle on "...WITH A" / "...IS".
_WEAK = {"a", "an", "the", "and", "or", "but", "to", "of", "in", "on", "for", "with", "is", "are",
         "it", "that", "as", "at", "by", "this", "your", "you", "we", "so", "its", "their", "a"}

def _phrase_chunks(words: list[tuple[str, float, float]], max_n: int) -> list[list]:
    """Group timed words into phrase-aware caption chunks: up to max_n words, break early on sentence
    punctuation, and never end a chunk on a weak function word (so captions don't dangle on 'A'/'IS')."""
    out: list[list] = []
    i, n = 0, len(words)
    while i < n:
        end = i
        while end < n and (end - i) < max_n:
            tok = words[end][0]
            end += 1
            if tok and tok[-1] in ".!?;:,":
                break
        while (end - i) > 1 and end < n:
            last = words[end - 1][0].strip(".,!?;:'\"").lower()
            if last in _WEAK:
                end -= 1
            else:
                break
        out.append(words[i:end])
        i = end
    # Eliminate orphan single-word chunks (sentence-end / weak-trim artifacts) so captions never flash
    # one tiny word. Fold each single into a neighbor: previous if it has room, else the next chunk.
    merged: list[list] = []
    for c in out:
        if len(c) == 1 and merged and len(merged[-1]) <= max_n:
            merged[-1] = merged[-1] + c
        else:
            merged.append(c)
    fixed: list[list] = []
    j = 0
    while j < len(merged):
        c = merged[j]
        if len(c) == 1 and j + 1 < len(merged) and len(merged[j + 1]) <= max_n:
            fixed.append(c + merged[j + 1])
            j += 2
        else:
            fixed.append(c)
            j += 1
    return fixed

def _fit_size(chars: int, box_w: int, cap: int) -> int:
    # Anton caps run ~0.46x the font size; size so the line fits the caption box width.
    return max(48, min(cap, int(box_w / (0.46 * max(chars, 1)))))

def caption_clips(text: str, seconds: float, style: Style,
                  words: list[tuple[str, float, float]] | None = None) -> list[TextClip]:
    """Word/phrase-synced captions — the #1 'this is a reel' signal. With a voiceover (`words` = per-
    word timings) it renders phrase-aware chunks with a per-word KARAOKE highlight (the spoken word
    pops in an accent color). Without a voiceover it spreads simple chunks evenly across the scene."""
    box_w = style.width - 160

    if not words:
        chunks = [c for c in _chunks(text, style.words_per_chunk) if c]
        if not chunks:
            return []
        span = seconds / len(chunks)
        size = _fit_size(max((len(c) for c in chunks), default=1), box_w, style.caption_size)
        box_h = int(style.height * 0.30)
        y_top = int(style.caption_y * style.height - box_h / 2)
        out: list[TextClip] = []
        for i, c in enumerate(chunks):
            disp = _clean_caption(c).upper()
            if not disp:
                continue
            out.append(
                TextClip(text=disp, font=style.font_path, font_size=size,
                         color=style.caption_color, stroke_color=style.caption_stroke,
                         stroke_width=style.caption_stroke_width, method="caption",
                         size=(box_w, box_h), text_align="center", horizontal_align="center",
                         vertical_align="center")
                .with_position(("center", y_top)).with_start(i * span).with_duration(span))
        return out

    out = []
    for chunk in _phrase_chunks(words, style.words_per_chunk):
        toks = [(_clean_caption(w).upper(), s, d) for (w, s, d) in chunk]
        toks = [(w, s, d) for (w, s, d) in toks if w]
        if not toks:
            continue
        c_start = toks[0][1]
        c_dur = max(toks[-1][1] + toks[-1][2] - c_start, 0.1)
        # A centered row of per-word clips: white base for the whole chunk + an accent overlay during
        # each word's spoken window (the karaoke highlight). _fit_row sizes the row to never overflow.
        cells, gap, total = _fit_row(toks, style, box_w)
        x = (style.width - total) / 2
        # Position by the GLYPH's real center (not the clip box): Anton's caps sit low in the metric
        # box, so box-centering drifts the visible text down. All words share size/height -> measure
        # once on the first clip and put that glyph center on caption_y.
        gc = _glyph_center(cells[0][0])
        y = int(style.caption_y * style.height - gc)
        for base, hot, s, d in cells:
            out.append(base.with_position((int(x), y)).with_start(c_start).with_duration(c_dur))
            hot = _pop(hot, int(x), y, x + base.w / 2.0, y + gc, style.caption_pop,
                       min(0.16, max(d, 0.08)))
            out.append(hot.with_start(s).with_duration(max(d, 0.08)))
            x += base.w + gap
    return out


def _pop(clip, x0: int, y0: int, px: float, py: float, amp: float, dur: float):
    """Scale-bounce a word as it lights up: scale amp->0 over dur, pivoting on the glyph center
    (px, py) so the letters grow IN PLACE over the static white base. amp<=0 disables the pop."""
    if amp <= 0:
        return clip.with_position((int(x0), int(y0)))
    sc = lambda t: 1.0 + amp * max(0.0, 1.0 - t / dur)
    return clip.resized(sc).with_position(lambda t: (px - (px - x0) * sc(t), py - (py - y0) * sc(t)))


def _glyph_center(clip) -> float:
    """The vertical pixel center of the actual (non-transparent) text in a caption clip — used to put
    the visible glyph on caption_y regardless of the font's metric ascent/descent asymmetry."""
    import numpy as np
    try:
        a = clip.mask.get_frame(0) if clip.mask is not None else (clip.get_frame(0).sum(2) > 20)
        rows = np.where(np.asarray(a).max(axis=1) > 0.1)[0]
        if len(rows):
            return float((int(rows.min()) + int(rows.max())) / 2)
    except Exception:
        pass
    return clip.h / 2


def _fit_row(toks: list[tuple[str, float, float]], style: Style, box_w: int):
    """Build the per-word row, then shrink the font until the measured width fits box_w (label clips
    add stroke padding + gaps the char estimate can't see, so iterate to convergence)."""
    joined = " ".join(w for w, _s, _d in toks)
    size = _fit_size(len(joined), box_w, style.caption_size)
    cells, gap, total = _build_row(toks, size, style)
    guard = 0
    while total > box_w and size > 44 and guard < 4:
        size = max(44, int(size * box_w / total) - 1)
        cells, gap, total = _build_row(toks, size, style)
        guard += 1
    return cells, gap, total


def _build_row(toks: list[tuple[str, float, float]], size: int, style: Style):
    """Render base+accent clips for each word at `size` and return (cells, gap, total_width).
    Each word is drawn in a PADDED caption box (not a tight `label`). Anton is a tall display face
    whose caps + bottom stroke sit LOW in the metric box, so a tight box shaves the glyph bottom (the
    'S' cut). Pad GENEROUSLY in height -- free, since the box is centered at caption_y so the extra
    height is invisible -- and modestly in width."""
    sw = style.caption_stroke_width
    pad_w = sw * 2 + int(size * 0.12)
    pad_h = sw * 4 + int(size * 0.9)
    cells = []
    for w, s, d in toks:
        m = TextClip(text=w, font=style.font_path, font_size=size, stroke_width=sw, method="label")
        box = (m.w + pad_w, m.h + pad_h)
        base = TextClip(text=w, font=style.font_path, font_size=size,
                        color=style.caption_color, stroke_color=style.caption_stroke,
                        stroke_width=sw, method="caption", size=box,
                        text_align="center", horizontal_align="center", vertical_align="center")
        hot = TextClip(text=w, font=style.font_path, font_size=size,
                       color=style.caption_active, stroke_color=style.caption_stroke,
                       stroke_width=sw, method="caption", size=box,
                       text_align="center", horizontal_align="center", vertical_align="center")
        cells.append((base, hot, s, d))
    gap = int(size * 0.06)   # boxes already carry width padding, so the inter-box gap is small
    total = sum(b.w for b, _h, _s, _d in cells) + gap * (len(cells) - 1)
    return cells, gap, total
