"""services.delivery — channel factory + the Orchestrator's cadence/target gating (offline)."""
import sys
import unittest
from types import SimpleNamespace
from unittest import mock
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from ai_scout.domain.cadence import Cadence  # noqa: E402
from ai_scout.domain.profile import Profile  # noqa: E402
from ai_scout.domain.user import User  # noqa: E402
from ai_scout.repositories.registry import UserRegistry  # noqa: E402
from ai_scout.services.delivery import orchestrator as orch  # noqa: E402
from ai_scout.services.delivery.email_sink import EmailSink  # noqa: E402
from ai_scout.services.delivery.digest_sink import DigestSink  # noqa: E402
from ai_scout.services.delivery.draft_sink import DraftSink  # noqa: E402


def _registry():
    user = User(id="usr_a", role="owner", profiles=[
        Profile(user_id="usr_a", id="prf_main", channel="email", cadence=Cadence.DAILY),
        Profile(user_id="usr_a", id="prf_reel", channel="draft", cadence=Cadence.ON_DEMAND,
                format="reel"),
    ])
    return UserRegistry([user])


class TestFactory(unittest.TestCase):
    def test_maps_channels_to_sinks(self):
        self.assertIsInstance(orch.make_sink("email"), EmailSink)
        self.assertIsInstance(orch.make_sink("digest"), DigestSink)
        self.assertIsInstance(orch.make_sink("draft"), DraftSink)

    def test_unknown_channel_raises(self):
        with self.assertRaises(ValueError):
            orch.make_sink("carrier-pigeon")

    def test_draft_sink_is_deterministic(self):
        self.assertEqual(DraftSink.explore_ratio, 0.0)
        self.assertIsNone(EmailSink.explore_ratio)


class TestOrchestratorGating(unittest.TestCase):
    def _orchestrator(self, sel):
        kb = SimpleNamespace(last_sent_ts=lambda lens: None, mark_sent=lambda lens, ids: None)
        embedder = SimpleNamespace(embed_interest=lambda interest: None)
        selector = SimpleNamespace(select=sel)
        return orch.Orchestrator(kb, _registry(), embedder, selector, None, None, None, {})

    def test_scheduled_pass_skips_on_demand_and_honors_cadence(self):
        sel = mock.Mock(return_value=[])
        self._orchestrator(sel).run()
        lenses = [c.args[0] for c in sel.call_args_list]
        self.assertEqual(lenses, ["usr_a:prf_main"])     # on_demand draft skipped

    def test_manual_targets_run_exactly_those_bypassing_cadence(self):
        sel = mock.Mock(return_value=[])
        self._orchestrator(sel).run(targets={"usr_a:prf_reel"})
        lenses = [c.args[0] for c in sel.call_args_list]
        self.assertEqual(lenses, ["usr_a:prf_reel"])     # only the requested on-demand lens


if __name__ == "__main__":
    unittest.main()
