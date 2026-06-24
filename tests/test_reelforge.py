import subprocess
import tempfile
import unittest
from pathlib import Path

import imageio_ffmpeg

from reelforge import Scene, Storyboard, Style, render
from reelforge.render.captions import _chunks
from reelforge.render.fonts import resolve_font

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

    def test_empty_storyboard_raises(self):
        with self.assertRaises(ValueError):
            render(Storyboard(scenes=[]), "x.mp4")

if __name__ == "__main__":
    unittest.main()
