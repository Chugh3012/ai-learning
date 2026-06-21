import sys
import tempfile
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
from ai_scout.services.delivery import delivery_sink as dsink
from ai_scout.services.delivery.sink import DeliveryContext
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

class _FakeBlob:
    def __init__(self, enabled=True):
        self.enabled = enabled
        self.writes = {}

    def put_text(self, path, text):
        self.writes[path] = text
        return True

class TestBlobLedger(unittest.TestCase):
    def _ctx(self, profile, blob, settings=None):
        items = [SimpleNamespace(id=1, title="One", url="http://a"),
                 SimpleNamespace(id=2, title="Two", url="http://b")]
        brief_builder = SimpleNamespace(build=lambda lens, items: None)
        feedback_store = SimpleNamespace(mint_tokens=lambda lens, rows: {})
        s = settings or SimpleNamespace(feedback_url="")
        return DeliveryContext(profile, items, s, brief_builder, feedback_store, blob)

    def test_digest_writes_per_profile_record_to_blob(self):
        prof = Profile(user_id="usr_a", id="prf_main", channel="digest",
                       cadence=Cadence.DAILY, name="Radar")
        blob = _FakeBlob(enabled=True)
        with mock.patch.object(dsink.BriefBuilder, "render", return_value=("PLAIN", "HTML")):
            ok = DigestSink().deliver(self._ctx(prof, blob))
        self.assertTrue(ok)
        self.assertEqual(len(blob.writes), 1)
        path, text = next(iter(blob.writes.items()))
        self.assertTrue(path.startswith("digests/usr_a-prf_main-"))
        self.assertTrue(path.endswith(".md"))
        self.assertIn("<!-- items: 1,2 -->", text)
        self.assertIn("PLAIN", text)

    def test_falls_back_to_local_scratch_when_blob_off(self):
        prof = Profile(user_id="usr_a", id="prf_x", channel="digest", cadence=Cadence.DAILY)
        with tempfile.TemporaryDirectory() as d:
            with mock.patch.object(dsink, "SCRATCH_DIR", Path(d)), \
                 mock.patch.object(dsink.BriefBuilder, "render", return_value=("PLAIN", "HTML")):
                ok = DigestSink().deliver(self._ctx(prof, _FakeBlob(enabled=False)))
            files = list((Path(d) / "digests").glob("*.md"))
            self.assertTrue(ok)
            self.assertEqual(len(files), 1)
            self.assertIn("<!-- items: 1,2 -->", files[0].read_text(encoding="utf-8"))

    def test_blob_record_written_even_when_email_unconfigured(self):
        prof = Profile(user_id="usr_a", id="prf_main", channel="email",
                       cadence=Cadence.DAILY, email_var="EMAIL_TO")
        blob = _FakeBlob(enabled=True)
        s = SimpleNamespace(feedback_url="", acs_endpoint="", email_sender="",
                            email_address=lambda var: "")
        with mock.patch.object(dsink.BriefBuilder, "render", return_value=("PLAIN", "HTML")):
            ok = EmailSink().deliver(self._ctx(prof, blob, s))
        self.assertFalse(ok)
        self.assertEqual(len(blob.writes), 1)

    def test_preference_url_includes_profile_id(self):
        prof = Profile(user_id="usr_a", id="prf_main", channel="email",
                       cadence=Cadence.DAILY, unsubscribe_token="tok")
        s = SimpleNamespace(feedback_url="", preference_url="https://fn/api/preferences")
        ctx = self._ctx(prof, _FakeBlob(enabled=False), s)
        self.assertEqual(
            dsink.DeliverySink._preference_url(ctx),
            "https://fn/api/preferences?t=tok&p=prf_main",
        )

    def test_saved_url_includes_profile_id(self):
        prof = Profile(user_id="usr_a", id="prf_main", channel="email",
                       cadence=Cadence.DAILY, unsubscribe_token="tok")
        s = SimpleNamespace(feedback_url="", saved_url="https://fn/api/saved")
        ctx = self._ctx(prof, _FakeBlob(enabled=False), s)
        self.assertEqual(
            dsink.DeliverySink._saved_url(ctx),
            "https://fn/api/saved?t=tok&p=prf_main",
        )

if __name__ == "__main__":
    unittest.main()
