import subprocess
import tempfile
import unittest
import wave
from pathlib import Path

import imageio_ffmpeg

from reelforge import Scene, Storyboard, Style, render
from reelforge.render.captions import _chunks
from reelforge.render.fonts import resolve_font
from reelforge.providers.tts.base import Speech, chunk_word_timings, wav_duration

def _silent_wav(path: Path, seconds: float = 0.5, rate: int = 16000) -> None:
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(b"\x00\x00" * int(rate * seconds))

class _FakeTTS:
    """A deterministic offline voiceover stub: writes a real silent wav + plausible word timings,
    so the render integration is testable in CI without touching Azure."""

    def synth(self, text: str, out_path: Path) -> Speech:
        _silent_wav(out_path, 0.5)
        words = [(w, i * 0.1, 0.1) for i, w in enumerate(text.split())]
        return Speech(audio_path=Path(out_path), words=words, duration=0.5)

class TestReelforge(unittest.TestCase):
    def test_renders_a_vertical_captioned_video(self):
        # Low fps + short scenes keep the render fast in CI; we only assert it's a real vertical clip.
        fast = Style(fps=8)
        sb = Storyboard(style=fast, scenes=[
            Scene(kicker="AI RADAR", text="Today in AI", seconds=0.5),
            Scene(kicker="01 / 01", text="Local models are good now", seconds=0.6),
        ])
        with tempfile.TemporaryDirectory() as d:
            out = render(sb, Path(d) / "r.mp4")
            self.assertTrue(out.exists())
            self.assertGreater(out.stat().st_size, 1000)
            probe = subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(), "-i", str(out)],
                                   capture_output=True, text=True)
            self.assertIn("1080x1920", probe.stderr)
            self.assertIn("Video:", probe.stderr)

    def test_bundled_font_is_resolved(self):
        font = resolve_font()
        self.assertIsNotNone(font)
        self.assertTrue(font.endswith(".ttf"))

    def test_caption_chunking(self):
        self.assertEqual(_chunks("a b c d e", 3), ["a b c", "d e"])
        self.assertEqual(_chunks("", 3), [""])

    def test_clean_caption_strips_stray_punctuation(self):
        from reelforge.render.captions import _clean_caption
        self.assertEqual(_clean_caption(", from text"), "from text")
        self.assertEqual(_clean_caption("AI's versatility ."), "AI's versatility")
        self.assertEqual(_clean_caption("and developers ."), "and developers")

    def test_empty_storyboard_raises(self):
        with self.assertRaises(ValueError):
            render(Storyboard(scenes=[]), "x.mp4")

class TestVoiceover(unittest.TestCase):
    def test_chunk_word_timings(self):
        words = [("a", 0.0, 0.2), ("b", 0.3, 0.2), ("c", 0.6, 0.2)]
        out = chunk_word_timings(words, 2)
        self.assertEqual([c[0] for c in out], ["a b", "c"])
        self.assertAlmostEqual(out[0][1], 0.0)        # chunk starts at first word
        self.assertAlmostEqual(out[0][2], 0.5)        # spans to end of "b" (0.3+0.2)

    def test_wav_duration(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "s.wav"
            _silent_wav(p, 0.5)
            self.assertAlmostEqual(wav_duration(p), 0.5, places=2)

    def test_render_with_voiceover_muxes_audio(self):
        sb = Storyboard(style=Style(fps=8), scenes=[
            Scene(kicker="01", text="local models are good"),
            Scene(text="prompt optimization works"),
        ])
        with tempfile.TemporaryDirectory() as d:
            out = render(sb, Path(d) / "r.mp4", tts=_FakeTTS())
            probe = subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(), "-i", str(out)],
                                   capture_output=True, text=True)
            self.assertIn("1080x1920", probe.stderr)
            self.assertIn("Audio:", probe.stderr)   # voiceover was muxed

class _FakeVisuals:
    """Offline b-roll stub: a flat color clip, so the b-roll + scrim path is testable without Pexels."""

    def __init__(self):
        self.closed = False

    def background(self, query, seconds, style, tmp):
        from moviepy import ColorClip
        return ColorClip((style.width, style.height), color=(12, 40, 12)).with_duration(seconds)

    def close(self):
        self.closed = True

class TestBroll(unittest.TestCase):
    def test_render_with_broll_provider(self):
        vis = _FakeVisuals()
        sb = Storyboard(style=Style(fps=8), scenes=[
            Scene(kicker="01", text="local models are good", seconds=0.6),
        ])
        with tempfile.TemporaryDirectory() as d:
            out = render(sb, Path(d) / "r.mp4", visuals=vis)
            probe = subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(), "-i", str(out)],
                                   capture_output=True, text=True)
            self.assertIn("1080x1920", probe.stderr)
        self.assertTrue(vis.closed)   # provider was closed after render

    def test_pexels_without_key_returns_none(self):
        from reelforge.providers.visuals.pexels import PexelsVisuals
        with tempfile.TemporaryDirectory() as d:
            self.assertIsNone(PexelsVisuals("").background("ai", 2.0, Style(), Path(d)))

if __name__ == "__main__":
    unittest.main()
