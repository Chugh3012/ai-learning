from __future__ import annotations

import os
from pathlib import Path

from moviepy import AudioFileClip, CompositeVideoClip, TextClip, concatenate_videoclips

from reelforge.domain.storyboard import Scene, Storyboard
from reelforge.domain.style import Style, hexrgb
from reelforge.render.backgrounds import gradient_bg
from reelforge.render.captions import caption_clips
from reelforge.render.fonts import resolve_font

def _scene_clip(scene: Scene, style: Style) -> CompositeVideoClip:
    layers = [gradient_bg(scene.seconds, style).with_position("center")]
    if scene.kicker:
        layers.append(
            TextClip(text=scene.kicker.upper(), font=style.font_path,
                     font_size=style.kicker_size, color=hexrgb(style.accent), method="label")
            .with_position(("center", int(style.height * 0.18))).with_duration(scene.seconds))
    layers += caption_clips(scene.text, scene.seconds, style)
    return CompositeVideoClip(layers, size=(style.width, style.height)).with_duration(scene.seconds)

def render(storyboard: Storyboard, out_path: str | Path) -> Path:
    """Render a Storyboard to a vertical mp4."""
    style = storyboard.style
    if not style.font_path:
        style.font_path = resolve_font() or ""
    if not storyboard.scenes:
        raise ValueError("reelforge: storyboard has no scenes")

    video = concatenate_videoclips([_scene_clip(s, style) for s in storyboard.scenes],
                                   method="compose")
    has_music = bool(storyboard.music and os.path.exists(storyboard.music))
    if has_music:
        track = AudioFileClip(storyboard.music)
        video = video.with_audio(track.subclipped(0, min(track.duration, video.duration)))

    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    video.write_videofile(str(out_path), fps=style.fps, codec="libx264",
                          audio_codec="aac" if has_music else None, audio=has_music,
                          logger=None)
    return out_path
