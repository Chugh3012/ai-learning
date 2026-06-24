import unittest

from prism.cli.reel import groundable
from prism.domain.cadence import Cadence
from prism.services.reel_script import ReelScripter
from prism.services.reel_playbook import load_playbook, Playbook


class _FakeScripter:
    def script_deep(self, title, body, system):
        return ("hook", [("Beat one.", "city"), ("Beat two.", "lab"), ("Beat three.", "robot")])

    def script(self, items, system):
        return ("Today in AI", {i: (f"H{i}", f"line {i}", f"q{i}") for i, *_ in items})


class _Row:
    def __init__(self, i):
        self.id, self.title, self.summary = i, f"T{i}", "s"


class TestReelScript(unittest.TestCase):
    def test_no_endpoint_is_a_graceful_noop(self):
        hook, cards = ReelScripter("", "m").script([(1, "Title", "Summary")])
        self.assertEqual((hook, cards), ("", {}))

    def test_no_items_is_a_noop(self):
        self.assertEqual(ReelScripter("https://x", "m").script([]), ("", {}))


class TestPlaybook(unittest.TestCase):
    def test_default_playbook_loads_and_joins_prompt(self):
        pb = load_playbook("explainer")
        self.assertEqual(pb.name, "explainer")
        self.assertIn("HOOK", pb.deep_system)        # array-of-lines joined into one brief
        self.assertTrue(pb.cta)

    def test_missing_playbook_falls_back(self):
        pb = load_playbook("does-not-exist")
        self.assertEqual(pb.deep_system, "")          # empty -> ReelScripter uses its default
        self.assertEqual(pb.name, "does-not-exist")


class TestPlaybookScenes(unittest.TestCase):
    # The playbook OWNS turning a script into scenes — no free helper functions in the CLI.
    def test_deep_scenes_are_hook_first_and_end_on_cta(self):
        pb = Playbook(deep_beats=3, cta="Follow.", outro_query="abstract")
        scenes = pb.deep_scenes("Title", "body", _FakeScripter())
        self.assertEqual(scenes[0].text, "Beat one.")     # scene 1 IS the hook beat
        self.assertEqual(scenes[-1].text, "Follow.")       # ends on the CTA
        self.assertEqual(len(scenes), 4)                   # 3 beats + cta

    def test_deep_scenes_respects_deep_beats(self):
        pb = Playbook(deep_beats=2)
        self.assertEqual(len(pb.deep_scenes("T", "b", _FakeScripter())), 3)   # 2 beats + cta

    def test_roundup_scenes_open_with_hook_and_one_card_per_story(self):
        pb = Playbook(cta="Follow.")
        scenes = pb.roundup_scenes([_Row(1), _Row(2)], _FakeScripter())
        self.assertEqual(scenes[0].text, "Today in AI")
        self.assertEqual(len(scenes), 4)                   # hook + 2 cards + cta


class TestPauseSemantics(unittest.TestCase):
    # A reel feed on the on_demand cadence is PAUSED: the renderer skips it (no auto-render/fallback).
    def test_on_demand_is_paused_scheduled_is_active(self):
        self.assertFalse(Cadence.from_name("on_demand").scheduled)
        self.assertTrue(Cadence.from_name("daily").scheduled)


class TestGroundable(unittest.TestCase):
    # A deep reel invents details from a near-empty source, so thin clickbait sources are skipped
    # and the next groundable ranked item is taken instead.
    def test_skips_thin_sources_and_takes_next_groundable(self):
        pool = ["a", "b", "c", "d"]
        body = {"a": "x" * 400, "b": "x" * 50, "c": "x" * 1500, "d": "x" * 2000}
        picks = groundable(pool, 2, 1000, lambda c: body[c])
        self.assertEqual([c for c, _ in picks], ["c", "d"])      # a, b too thin -> skipped

    def test_returns_fewer_when_nothing_is_thick_enough(self):
        picks = groundable(["a", "b"], 2, 1000, lambda c: "x" * 100)
        self.assertEqual(picks, [])


if __name__ == "__main__":
    unittest.main()
