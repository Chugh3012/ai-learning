"""sinks — channel factory + the orchestrator's cadence/target gating (offline, mocked Azure)."""
import sqlite3
import sys
import unittest
from unittest import mock
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))
import sinks  # noqa: E402
from profiles import User, Profile, cadence  # noqa: E402


def _con():
    con = sqlite3.connect(":memory:")
    con.execute("CREATE TABLE signal(id INTEGER PRIMARY KEY, item_id INTEGER, kind TEXT, "
                "value REAL, ts INTEGER)")
    return con


def _users():
    return [User(id="usr_a", role="owner", profiles=[
        Profile(user_id="usr_a", id="prf_main", channel="email", cadence=cadence("daily")),
        Profile(user_id="usr_a", id="prf_reel", channel="draft", cadence=cadence("on_demand"),
                format="reel"),
    ])]


class TestFactory(unittest.TestCase):
    def test_maps_channels_to_sinks(self):
        self.assertIsInstance(sinks.make_sink("email"), sinks.EmailSink)
        self.assertIsInstance(sinks.make_sink("digest"), sinks.DigestSink)
        self.assertIsInstance(sinks.make_sink("draft"), sinks.DraftSink)

    def test_unknown_channel_raises(self):
        with self.assertRaises(ValueError):
            sinks.make_sink("carrier-pigeon")

    def test_draft_sink_is_deterministic(self):
        self.assertEqual(sinks.DraftSink.explore_ratio, 0.0)   # never gamble a production slot
        self.assertIsNone(sinks.EmailSink.explore_ratio)       # delivery uses the config default


class TestOrchestratorGating(unittest.TestCase):
    def test_scheduled_pass_skips_on_demand_and_honors_cadence(self):
        con = _con()
        self.addCleanup(con.close)
        with mock.patch.object(sinks, "select_items", return_value=[]) as sel, \
             mock.patch("embed.embed_interest", return_value=None):
            sinks.deliver_all(con, _users(), {}, "ep", "model")
        lenses = [c.args[1] for c in sel.call_args_list]
        self.assertEqual(lenses, ["usr_a:prf_main"])           # on_demand draft skipped

    def test_manual_targets_run_exactly_those_bypassing_cadence(self):
        con = _con()
        self.addCleanup(con.close)
        with mock.patch.object(sinks, "select_items", return_value=[]) as sel, \
             mock.patch("embed.embed_interest", return_value=None):
            sinks.deliver_all(con, _users(), {}, "ep", "model", targets={"usr_a:prf_reel"})
        lenses = [c.args[1] for c in sel.call_args_list]
        self.assertEqual(lenses, ["usr_a:prf_reel"])           # only the requested on-demand lens


if __name__ == "__main__":
    unittest.main()
