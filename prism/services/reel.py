from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path

import imageio_ffmpeg
from PIL import Image, ImageDraw, ImageFont

# Brand palette (matches the marketing site).
PAPER = (243, 239, 228)
INK = (26, 23, 18)
MUTED = (120, 112, 100)
COBALT = (36, 56, 224)

W, H = 1080, 1920  # vertical 9:16, the reel canvas
MARGIN = 96

# Font candidates per platform; falls back to Pillow's default if none resolve. ponytail: a
# bundled brand font would look better, but system fonts keep the repo asset-free for v1.
_BOLD = ["C:/Windows/Fonts/arialbd.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
         "/Library/Fonts/Arial Bold.ttf"]
_REG = ["C:/Windows/Fonts/arial.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/Library/Fonts/Arial.ttf"]


def _font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    for path in (_BOLD if bold else _REG):
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            continue
    return ImageFont.load_default(size)


def _wrap(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.FreeTypeFont, max_w: int) -> list[str]:
    lines: list[str] = []
    cur = ""
    for word in text.split():
        trial = f"{cur} {word}".strip()
        if draw.textlength(trial, font=font) <= max_w or not cur:
            cur = trial
        else:
            lines.append(cur)
            cur = word
    if cur:
        lines.append(cur)
    return lines


def _draw_block(draw, text, font, x, y, max_w, fill, leading) -> int:
    for line in _wrap(draw, text, font, max_w):
        draw.text((x, y), line, font=font, fill=fill)
        y += leading
    return y


def _card(kicker: str, headline: str, body: str, footer: str) -> Image.Image:
    img = Image.new("RGB", (W, H), PAPER)
    d = ImageDraw.Draw(img)
    d.rectangle([0, 0, 12, H], fill=COBALT)  # left accent rail
    if kicker:
        kf = _font(40, bold=True)
        d.text((MARGIN, 150), kicker.upper(), font=kf, fill=COBALT)
    y = 320
    y = _draw_block(d, headline, _font(78, bold=True), MARGIN, y, W - 2 * MARGIN, INK, 92)
    if body:
        y += 56
        _draw_block(d, body, _font(50), MARGIN, y, W - 2 * MARGIN, INK, 66)
    if footer:
        d.text((MARGIN, H - 170), footer, font=_font(36), fill=MUTED)
    return img


def _ffmpeg() -> str:
    return imageio_ffmpeg.get_ffmpeg_exe()


class ReelMaker:
    """Render a vertical MP4 'AI radar' update from ranked items. Pure Pillow + ffmpeg, no cloud."""

    def __init__(self, seconds_per_card: float = 3.5):
        self.seconds = seconds_per_card

    def _slides(self, title: str, items: list[dict], outro: str) -> list[tuple[Image.Image, float]]:
        slides = [(_card("AI RADAR", title, "", "swipe through today's signal"), self.seconds)]
        for i, it in enumerate(items, 1):
            slides.append((_card(f"{i:02d} / {len(items):02d}",
                                 it.get("headline", ""), it.get("takeaway", ""),
                                 it.get("source", "")), self.seconds))
        if outro:
            slides.append((_card("", outro, "", ""), self.seconds))
        return slides

    def build(self, items: list[dict], out_path: str | Path, title: str = "Today in AI",
              outro: str = "", music: str | Path | None = None) -> Path:
        out_path = Path(out_path)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        slides = self._slides(title, items, outro)
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            listing: list[str] = []
            for idx, (img, secs) in enumerate(slides):
                p = tmp_path / f"card{idx:03d}.png"
                img.save(p)
                listing.append(f"file '{p.as_posix()}'\nduration {secs}")
            # concat demuxer ignores the final duration unless the last file is repeated.
            listing.append(f"file '{(tmp_path / f'card{len(slides) - 1:03d}.png').as_posix()}'")
            concat = tmp_path / "list.txt"
            concat.write_text("\n".join(listing), encoding="utf-8")

            cmd = [_ffmpeg(), "-y", "-f", "concat", "-safe", "0", "-i", str(concat)]
            if music:
                cmd += ["-i", str(music)]
            cmd += ["-vf", "scale=1080:1920,format=yuv420p", "-r", "30", "-c:v", "libx264"]
            if music:
                cmd += ["-c:a", "aac", "-shortest"]
            cmd += ["-movflags", "+faststart", str(out_path)]
            subprocess.run(cmd, check=True, capture_output=True)
        return out_path
