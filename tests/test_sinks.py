import sys
import unittest
from types import SimpleNamespace
from unittest import mock
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from ai_scout.domain.cadence import Cadence
from ai_scout.domain.profile import Profile
from ai_scout.domain.user import User
from ai_scout.repositories.registry import UserRegistry
from ai_scout.services.delivery import orchestrator as orch
from ai_scout.services.delivery.email_sink import EmailSink
from ai_scout.services.delivery.digest_sink import DigestSink

def _registry():
    user = User(id="usr_a", role="owner", profiles=[
        Profile(user_id="usr_a", id="prf_main", channel="email", cadence=Cadence.DAILY),
        Profile(user_id="usr_a", id="prf_reel", channel="digest", cadence=Cadence.ON_DEMAND),
    ])
    return UserRegistry([user])

class TestFactory(unittest.TestCase):
    def test_maps_channels_to_sinks(self):
        self.assertIsInstance(orch.make_sink("email"), EmailSink)
        self.assertIsInstance(orch.make_sink("digest"), DigestSink)

    def test_unknown_channel_raises(self):
        with self.assertRaises(ValueError):
            orch.make_sink("carrier-pigeon")

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
        self.assertEqual(lenses, ["usr_a:prf_main"])

    def test_manual_targets_run_exactly_those_bypassing_cadence(self):
        sel = mock.Mock(return_value=[])
        self._orchestrator(sel).run(targets={"usr_a:prf_reel"})
        lenses = [c.args[0] for c in sel.call_args_list]
        self.assertEqual(lenses, ["usr_a:prf_reel"])

if __name__ == "__main__":
    unittest.main()
