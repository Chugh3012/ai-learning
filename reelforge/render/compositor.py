from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

from moviepy import (AudioFileClip, ColorClip, CompositeVideoClip, TextClip,
                     concatenate_videoclips)

from reelforge.domain.storyboard import Scene, Storyboard
from reelforge.domain.style import Style, hexrgb
from reelforge.providers.tts.base import TTS
from reelforge.providers.visuals.base import Visual
from reelforge.render.backgrounds import gradient_bg
from reelforge.render.captions import caption_clips
from reelforge.render.fonts import resolve_font

# A tiny pad after the last spoken word so cuts don't feel clipped (the TTS trailing silence,
# which otherwise reads as a dead gap at every cut, is removed).
_TAIL = 0.12

def _grade(frame):
    # One cinematic grade across every scene so mixed stock feels like a single film: a touch more
    # contrast, a gentle shadow lift (so dark clips don't crush to black), and a warm push.
    f = frame.astype("float32")
    f = (f - 128.0) * 1.10 + 128.0
    f = f.clip(0.0, 255.0)
    f = 255.0 * (f / 255.0) ** 0.90          # gamma < 1 lifts shadows / midtones
    f[..., 0] *= 1.05                          # warm: lift red
    f[..., 2] *= 0.94                          # cool down blue
    return f.clip(0, 255).astype("uint8")

def _vignette_clip(w: int, h: int, strength: float, seconds: float):
    # A static edge-darkening overlay (black with a radial alpha that's 0 across most of the frame and
    # only rises near the CORNERS). Frame-aligned, so it stays at the edges even as the b-roll zooms.
    import numpy as np
    from moviepy import ImageClip
    yy, xx = np.mgrid[0:h, 0:w]
    r = np.sqrt(((xx - w / 2.0) / (w / 2.0)) ** 2 + ((yy - h / 2.0) / (h / 2.0)) ** 2)
    alpha = (strength * np.clip((r - 0.78) / 0.42, 0.0, 1.0)).astype("float32")
    base = ImageClip(np.zeros((h, w, 3), dtype="uint8")).with_duration(seconds)
    mask = ImageClip(alpha, is_mask=True).with_duration(seconds)
    return base.with_mask(mask)

def _scene_clip(scene: Scene, style: Style, tts: TTS | None, visuals: Visual | None,
                tmp: Path, idx: int, opened: list) -> CompositeVideoClip:
    speech = None
    if tts is not None and scene.text.strip():
        speech = tts.synth(scene.text, tmp / f"vo{idx:03d}.wav")

    # End the scene right after the LAST spoken word. Neural TTS wavs carry trailing silence that
    # otherwise plays as dead air at every cut; trimming to the last word keeps momentum high.
    if speech:
        last_word_end = max((st + dr for _w, st, dr in speech.words), default=speech.duration)
        seconds = min(speech.duration, last_word_end + _TAIL)
    else:
        seconds = scene.seconds

    broll = (visuals.background(scene.query or scene.text, seconds, style, tmp,
                                prompt=scene.visual_prompt) if visuals else None)
    if broll is not None:
        if style.grade:
            broll = broll.image_transform(_grade)
        # Slow push-in (Ken Burns) so static stock has momentum; a stronger HERO push on the hook.
        push = style.kenburns * (1.7 if idx == 0 else 1.0)
        if push > 0:
            broll = broll.resized(lambda t: 1.0 + push * (t / max(seconds, 0.1)))
        scrim = ColorClip((style.width, style.height), color=(0, 0, 0)).with_opacity(
            style.scrim).with_duration(seconds)
        layers = [broll.with_position("center"), scrim]
        if style.vignette > 0:
            layers.append(_vignette_clip(style.width, style.height, style.vignette, seconds))
    else:
        layers = [gradient_bg(seconds, style).with_position("center")]

    if scene.kicker:
        layers.append(
            TextClip(text=scene.kicker.upper(), font=style.font_path,
                     font_size=style.kicker_size, color=hexrgb(style.accent), method="label",
                     stroke_color=style.caption_stroke, stroke_width=style.kicker_stroke_width)
            .with_position(("center", int(style.height * 0.18))).with_duration(seconds))
    layers += caption_clips(scene.text, seconds, style, words=speech.words if speech else None)

    clip = CompositeVideoClip(layers, size=(style.width, style.height)).with_duration(seconds)
    if speech:
        voice = AudioFileClip(str(speech.audio_path))
        opened.append(voice)
        clip = clip.with_audio(voice.subclipped(0, min(voice.duration, seconds)))
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
        sfx = _sfx(clips) if style.sfx else []
        audio = _compose_audio(video.audio, music, sfx, style.music_volume)
        if audio is not None:
            video = video.with_audio(audio)

        has_audio = audio is not None
        video.write_videofile(str(out_path), fps=style.fps, codec="libx264",
                              bitrate=style.bitrate,
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

def _sfx(clips: list) -> list:
    # Build the sound-design layer: a riser under the hook + a whoosh just before each cut. Each piece
    # is independently graceful so a synth hiccup never sinks the render.
    starts, t = [], 0.0
    for c in clips:
        starts.append(t)
        t += float(c.duration)
    out: list = []
    try:
        from reelforge.render.sfx import riser_clip, whoosh_clip
    except Exception:
        return out
    try:
        out.append(riser_clip(min(1.2, starts[1] if len(starts) > 1 else 1.2)).with_start(0.0))
    except Exception:
        pass
    for st in starts[1:]:
        try:
            out.append(whoosh_clip().with_start(max(0.0, st - 0.10)))
        except Exception:
            pass
    return out

def _compose_audio(voice, music, sfx: list, volume: float):
    # One mix: ducked music bed + the sfx accents + the voiceover on top.
    from moviepy import CompositeAudioClip
    tracks = []
    if music is not None:
        tracks.append(music.with_volume_scaled(volume if voice is not None else min(0.6, volume * 4)))
    tracks.extend(sfx)
    if voice is not None:
        tracks.append(voice)
    return CompositeAudioClip(tracks) if tracks else None
