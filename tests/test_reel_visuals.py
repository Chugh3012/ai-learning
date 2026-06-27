import unittest
from pathlib import Path
from types import SimpleNamespace

from reelforge import FallbackVisuals, Scene, SoraVisuals
from prism.services.reel_visuals import make_visuals
from prism.services.reel_visual_prompt import VisualPromptWriter

_STYLE = SimpleNamespace(width=1080, height=1920)


def _settings(pexels="", endpoint="", sora="sora"):
    return SimpleNamespace(pexels_api_key=pexels, foundry_project_endpoint=endpoint,
                           foundry_sora_deployment=sora)


class _Recorder:
    """A fake Visual that records the prompt it was handed and returns a preset clip (or None)."""

    def __init__(self, clip):
        self.clip, self.seen_prompt, self.closed = clip, None, False

    def background(self, query, seconds, style, tmp, prompt=""):
        self.seen_prompt = prompt
        return self.clip

    def close(self):
        self.closed = True


class TestScene(unittest.TestCase):
    def test_scene_carries_a_visual_prompt_default_blank(self):
        self.assertEqual(Scene(text="hi").visual_prompt, "")
        self.assertEqual(Scene(visual_prompt="a glowing lattice").visual_prompt, "a glowing lattice")


class TestMakeVisuals(unittest.TestCase):
    def test_ai_off_no_key_is_none(self):
        self.assertIsNone(make_visuals(_settings(pexels=""), {}, ai_visuals=False))

    def test_ai_off_with_key_is_pexels(self):
        v = make_visuals(_settings(pexels="k"), {"visuals": "pexels"}, ai_visuals=False)
        self.assertEqual(type(v).__name__, "PexelsVisuals")

    def test_ai_on_is_fallback_ladder_with_sora_first(self):
        creative = {"sora": {"deployment": "sora", "size": "720x1280"}}
        v = make_visuals(_settings(pexels="k", endpoint="https://x"), creative, ai_visuals=True)
        self.assertIsInstance(v, FallbackVisuals)
        self.assertEqual(type(v.providers[0]).__name__, "SoraVisuals")
        self.assertEqual(type(v.providers[1]).__name__, "PexelsVisuals")

    def test_ai_on_without_pexels_is_sora_only(self):
        v = make_visuals(_settings(pexels="", endpoint="https://x"), {}, ai_visuals=True)
        self.assertIsInstance(v, FallbackVisuals)
        self.assertEqual([type(p).__name__ for p in v.providers], ["SoraVisuals"])

    def test_dry_run_propagates_to_sora(self):
        v = make_visuals(_settings(endpoint="https://x"), {}, ai_visuals=True, dry_run=True)
        self.assertTrue(v.providers[0].dry_run)


class TestFallbackVisuals(unittest.TestCase):
    def test_returns_first_non_none_and_passes_prompt(self):
        a, b = _Recorder(None), _Recorder("CLIP")
        fb = FallbackVisuals([a, b])
        out = fb.background("q", 4.0, _STYLE, Path("."), prompt="vivid shot")
        self.assertEqual(out, "CLIP")
        self.assertEqual(a.seen_prompt, "vivid shot")     # tried first
        self.assertEqual(b.seen_prompt, "vivid shot")     # fell through to second

    def test_all_none_returns_none(self):
        self.assertIsNone(FallbackVisuals([_Recorder(None), _Recorder(None)])
                          .background("q", 4.0, _STYLE, Path(".")))

    def test_drops_none_providers_and_closes_all(self):
        a, b = _Recorder("X"), _Recorder("Y")
        fb = FallbackVisuals([a, None, b])
        self.assertEqual(len(fb.providers), 2)
        fb.close()
        self.assertTrue(a.closed and b.closed)


class TestSoraVisuals(unittest.TestCase):
    def test_dry_run_returns_none_and_spends_nothing(self):
        sora = SoraVisuals(endpoint="https://acct/api/projects/p", dry_run=True)
        out = sora.background("data center", 5.0, _STYLE, Path("."), prompt="a river of light")
        self.assertIsNone(out)
        self.assertEqual(sora.spent_seconds, 0.0)

    def test_empty_text_is_none(self):
        self.assertIsNone(SoraVisuals(endpoint="https://x", dry_run=True)
                          .background("", 5.0, _STYLE, Path("."), prompt=""))

    def test_clip_seconds_snaps_to_allowed_and_caps(self):
        self.assertEqual(SoraVisuals._clip_seconds(3.7, 12), 4)
        self.assertEqual(SoraVisuals._clip_seconds(5.0, 12), 8)
        self.assertEqual(SoraVisuals._clip_seconds(9.0, 12), 12)
        self.assertEqual(SoraVisuals._clip_seconds(30.0, 8), 8)    # capped

    def test_budget_cap_falls_back(self):
        sora = SoraVisuals(endpoint="https://x", max_seconds=4, dry_run=True)
        sora.spent_seconds = 4.0                                   # already at budget
        self.assertIsNone(sora.background("q", 8.0, _STYLE, Path(".")))

    def test_account_strips_project_suffix(self):
        sora = SoraVisuals(endpoint="https://acct.services.ai.azure.com/api/projects/scout")
        self.assertEqual(sora._account(), "https://acct.services.ai.azure.com")


class TestVisualPromptWriter(unittest.TestCase):
    def test_no_endpoint_is_graceful_blanks(self):
        self.assertEqual(VisualPromptWriter("", "m").write("t", "b", ["a", "b"]), ["", ""])

    def test_no_beats_is_empty(self):
        self.assertEqual(VisualPromptWriter("https://x", "m").write("t", "b", []), [])

    def test_finish_weaves_shot_then_style_then_suffix(self):
        out = VisualPromptWriter._finish("  A glowing   neural lattice.  ", "teal palette, liquid light")
        self.assertTrue(out.startswith("A glowing neural lattice. teal palette, liquid light,"))
        self.assertIn("no text", out)
        self.assertIn("9:16", out)

    def test_finish_without_style_just_suffixes(self):
        self.assertTrue(VisualPromptWriter._finish("A river of data", "").startswith("A river of data,"))

    def test_finish_blank_shot_stays_blank(self):
        self.assertEqual(VisualPromptWriter._finish("   ", "any style"), "")


if __name__ == "__main__":
    unittest.main()
