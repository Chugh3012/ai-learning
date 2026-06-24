from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

from moviepy import (AudioFileClip, ColorClip, CompositeVideoClip, TextClip,
                     concatenate_videoclips)

from reelforge.domain.storyboard import Scene, Storyboard
from reelforge.domain.style import Style, hexrgb
from reelforge.providers.tts.base import TTS, chunk_word_timings
from reelforge.providers.visuals.base import Visual
from reelforge.render.backgrounds import gradient_bg
from reelforge.render.captions import caption_clips
from reelforge.render.fonts import resolve_font

# A short beat of silence after the voice finishes so cuts don't feel clipped.
_TAIL = 0.35

def _scene_clip(scene: Scene, style: Style, tts: TTS | None, visuals: Visual | None,
                tmp: Path, idx: int, opened: list) -> CompositeVideoClip:
    speech = None
    if tts is not None and scene.text.strip():
        speech = tts.synth(scene.text, tmp / f"vo{idx:03d}.wav")

    seconds = (speech.duration + _TAIL) if speech else scene.seconds

    broll = visuals.background(scene.query or scene.text, seconds, style, tmp) if visuals else None
    if broll is not None:
        scrim = ColorClip((style.width, style.height), color=(0, 0, 0)).with_opacity(
            style.scrim).with_duration(seconds)
        layers = [broll.with_position("center"), scrim]
    else:
        layers = [gradient_bg(seconds, style).with_position("center")]

    if scene.kicker:
        layers.append(
            TextClip(text=scene.kicker.upper(), font=style.font_path,
                     font_size=style.kicker_size, color=hexrgb(style.accent), method="label",
                     stroke_color=style.caption_stroke, stroke_width=2)
            .with_position(("center", int(style.height * 0.18))).with_duration(seconds))
    starts = chunk_word_timings(speech.words, style.words_per_chunk) if speech else None
    layers += caption_clips(scene.text, seconds, style, starts=starts)

    clip = CompositeVideoClip(layers, size=(style.width, style.height)).with_duration(seconds)
    if speech:
        voice = AudioFileClip(str(speech.audio_path))
        opened.append(voice)
        clip = clip.with_audio(voice)
    return clip

def render(storyboard: Storyboard, out_path: str | Path, tts: TTS | None = None,
           visuals: Visual | None = None) -> Path:
    """Render a Storyboard to a vertical mp4. Pass a `tts` provider for a synced voiceover (captions
    then follow the spoken word timings) and a `visuals` provider for stock b-roll behind each scene
    (a scrim keeps captions legible); both are optional and degrade gracefully."""
    style = storyboard.style
    if not style.font_path:
        style.font_path = resolve_font() or ""
    if not storyboard.scenes:
        raise ValueError("reelforge: storyboard has no scenes")

    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = Path(tempfile.mkdtemp(prefix="reelforge_"))
    opened: list = []        # audio readers to close before the temp dir is removed (Windows locks)
    video = None
    try:
        clips = [_scene_clip(s, style, tts, visuals, tmp, i, opened)
                 for i, s in enumerate(storyboard.scenes)]
        video = concatenate_videoclips(clips, method="compose")

        music = _music_bed(storyboard, video.duration, opened)
        if music is not None:
            video = video.with_audio(_mix(video.audio, music))

        has_audio = tts is not None or music is not None
        video.write_videofile(str(out_path), fps=style.fps, codec="libx264",
                              audio_codec="aac" if has_audio else None, audio=has_audio,
                              logger=None)
    finally:
        for clip in [video, *opened]:
            try:
                clip and clip.close()
            except Exception:
                pass
        if visuals is not None and hasattr(visuals, "close"):
            try:
                visuals.close()
            except Exception:
                pass
        shutil.rmtree(tmp, ignore_errors=True)
    return out_path

def _music_bed(storyboard: Storyboard, duration: float, opened: list):
    if not storyboard.music or not Path(storyboard.music).exists():
        return None
    track = AudioFileClip(storyboard.music)
    opened.append(track)
    return track.subclipped(0, min(track.duration, duration))

def _mix(voice, music):
    # Duck music under the voiceover; if there's no voice (silent captions), music carries alone.
    from moviepy import CompositeAudioClip
    music = music.with_volume_scaled(0.18 if voice is not None else 0.6)
    return CompositeAudioClip([music, voice]) if voice is not None else music
