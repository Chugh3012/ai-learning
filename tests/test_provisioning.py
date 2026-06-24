import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from prism.repositories.subscribers import SubscriberStore
from prism.domain.profile import Profile


class _Table:
    def __init__(self):
        self.rows: dict[tuple, dict] = {}

    def upsert_entity(self, e, mode=None):
        self.rows[(e["PartitionKey"], e["RowKey"])] = dict(e)

    def delete_entity(self, pk, rk):
        self.rows.pop((pk, rk), None)

    def query_entities(self, q, parameters=None):
        params = parameters or {}
        for (pk, _rk), e in list(self.rows.items()):
            if "PartitionKey eq 'sub'" in q:
                if pk != "sub":
                    continue
                if "kind eq @k" in q and str(e.get("kind")) != str(params.get("k")):
                    continue
                yield e
            elif "PartitionKey eq @u" in q and pk == (params.get("u") or params.get("uid")):
                yield e


class _Svc:
    def __init__(self):
        self.t = {"subscribers": _Table(), "profiles": _Table()}

    def get_table_client(self, name):
        return self.t[name]


def _store() -> SubscriberStore:
    st = SubscriberStore("acct")
    st._svc = _Svc()
    return st


class TestProvisioning(unittest.TestCase):
    def test_mints_generated_ids_and_is_idempotent(self):
        st = _store()
        uid, pid = st.provision_feed("reel", "ai", "interest A")
        self.assertTrue(uid.startswith("usr_") and len(uid) == 12)   # usr_ + 8 hex
        self.assertTrue(pid.startswith("prf_") and len(pid) == 12)
        # same kind+topic updates in place — no duplicate user/profile
        self.assertEqual((uid, pid), st.provision_feed("reel", "ai", "interest B"))
        # a second topic reuses the single reel user, new profile
        uid3, pid3 = st.provision_feed("reel", "politics", "interest C")
        self.assertEqual(uid3, uid)
        self.assertNotEqual(pid3, pid)

    def test_provisioned_feed_reads_back_as_a_lens(self):
        st = _store()
        uid, pid = st.provision_feed("reel", "ai", "scroll-stopping")
        profs = st._profiles_for(uid)
        self.assertEqual(len(profs), 1)
        p = Profile.from_dict(uid, profs[0])      # the registry's read mapping
        self.assertEqual(p.lens, f"{uid}:{pid}")
        self.assertEqual((p.channel, p.topic_id, p.interest), ("digest", "ai", "scroll-stopping"))

    def test_profile_schema_is_pinned(self):
        # CONTRACT: the standalone Function (writer, cannot import prism) and the registry (reader)
        # must agree on these profile field names. Pin them so any drift fails RED.
        st = _store()
        uid, _ = st.provision_feed("reel", "ai", "x")
        self.assertEqual(set(st._profiles_for(uid)[0]),
                         {"id", "name", "channel", "cadence", "top", "min_score",
                          "interest", "self_review", "topic_id"})

    def test_remove_feed(self):
        st = _store()
        st.provision_feed("reel", "ai", "a")
        st.provision_feed("reel", "politics", "b")
        self.assertEqual(st.remove_feed("reel", "ai"), 1)
        self.assertEqual({f["topic_id"] for f in st.list_feeds("reel")}, {"politics"})


class TestReconcile(unittest.TestCase):
    def test_provision_preserves_db_interest_when_none(self):
        # interest is db-owned: re-provisioning with interest=None must not clobber it.
        st = _store()
        st.provision_feed("reel", "ai", "keep me")
        uid, _ = st.provision_feed("reel", "ai", None, cadence="weekly", top=3)
        p = st._profiles_for(uid)[0]
        self.assertEqual(p["interest"], "keep me")     # preserved
        self.assertEqual(p["cadence"], "weekly")        # config updated

    def test_reconcile_ensures_enabled_and_removes_disabled(self):
        st = _store()
        st.provision_feed("reel", "politics", "pol")    # exists; will be disabled
        lines = st.reconcile_reels([
            {"topic": "ai", "enabled": True, "cadence": "daily", "reels": 2},
            {"topic": "politics", "enabled": False},
        ])
        self.assertEqual({f["topic_id"] for f in st.list_feeds("reel")}, {"ai"})
        self.assertEqual(len(lines), 2)

    def test_reconcile_preserves_interest_on_ensure(self):
        st = _store()
        st.provision_feed("reel", "ai", "my interest")
        st.reconcile_reels([{"topic": "ai", "enabled": True, "cadence": "daily", "reels": 2}])
        uid = st.list_feeds("reel")[0]["user_id"]
        self.assertEqual(st._profiles_for(uid)[0]["interest"], "my interest")


if __name__ == "__main__":
    unittest.main()
