import subprocess
import tempfile
import unittest
from pathlib import Path

import imageio_ffmpeg

from prism.services.reel import ReelMaker

class TestReel(unittest.TestCase):
    def test_build_produces_a_real_vertical_video(self):
        items = [
            {"headline": "A model ships", "takeaway": "It does a thing well.", "source": "x.com"},
            {"headline": "Another update", "takeaway": "It does another thing.", "source": "y.com"},
        ]
        with tempfile.TemporaryDirectory() as d:
            out = ReelMaker(seconds_per_card=1.0).build(items, Path(d) / "r.mp4", title="Today in AI")
            self.assertTrue(out.exists())
            self.assertGreater(out.stat().st_size, 1000)
            probe = subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(), "-i", str(out)],
                                   capture_output=True, text=True)
            # ffmpeg prints stream info to stderr; assert a vertical H.264 video stream exists.
            self.assertIn("Video:", probe.stderr)
            self.assertIn("1080x1920", probe.stderr)

    def test_no_items_still_renders_intro_outro(self):
        with tempfile.TemporaryDirectory() as d:
            out = ReelMaker(seconds_per_card=1.0).build([], Path(d) / "r.mp4", outro="bye")
            self.assertTrue(out.exists())

class TestReelScript(unittest.TestCase):
    def test_no_endpoint_is_a_graceful_noop(self):
        from prism.services.reel_script import ReelScripter
        hook, cards = ReelScripter("", "m").script([(1, "Title", "Summary")])
        self.assertEqual((hook, cards), ("", {}))

    def test_no_items_is_a_noop(self):
        from prism.services.reel_script import ReelScripter
        self.assertEqual(ReelScripter("https://x", "m").script([]), ("", {}))

if __name__ == "__main__":
    unittest.main()
