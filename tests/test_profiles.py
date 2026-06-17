import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from ai_scout.domain.cadence import Cadence
from ai_scout.repositories.registry import UserRegistry

class TestRegistry(unittest.TestCase):
    def setUp(self):
        self.reg = UserRegistry.load()

    def test_users_have_opaque_ids_and_roles(self):
        roles = {u.role for u in self.reg.users}
        self.assertIn("owner", roles)
        self.assertIn("builder", roles)
        for u in self.reg.users:
            self.assertTrue(u.id.startswith("usr_"))
            for p in u.profiles:
                self.assertTrue(p.id.startswith("prf_"))

    def test_user_by_role(self):
        m = self.reg.user_by_role("builder")
        self.assertIsNotNone(m)
        self.assertEqual(m.role, "builder")
        self.assertIsNone(self.reg.user_by_role("nobody"))

    def test_lens_is_composite_and_filesafe(self):
        p = self.reg.users[0].profiles[0]
        self.assertEqual(p.lens, f"{self.reg.users[0].id}:{p.id}")
        self.assertEqual(p.filesafe_lens, p.lens.replace(":", "-"))
        self.assertNotIn(":", p.filesafe_lens)

    def test_find_profile_by_lens(self):
        p0 = self.reg.profiles()[0]
        self.assertEqual(self.reg.find_profile(p0.lens), p0)
        self.assertIsNone(self.reg.find_profile("usr_x:prf_y"))

    def test_profile_for_role_prefers_self_review(self):
        prof = self.reg.profile_for_role("builder")
        self.assertTrue(prof.self_review)

    def test_feedback_lenses_excludes_draft(self):
        fl = self.reg.feedback_lenses()
        for p in self.reg.profiles():
            if p.channel == "draft":
                self.assertNotIn(p.lens, fl)
            else:
                self.assertIn(p.lens, fl)

class TestCadence(unittest.TestCase):
    def test_daily_due_when_never_sent_or_old(self):
        c = Cadence.DAILY
        self.assertTrue(c.scheduled)
        self.assertTrue(c.is_due(None, 1_000_000))
        self.assertTrue(c.is_due(1_000_000 - 2 * 86400, 1_000_000))

    def test_weekly_holds_until_interval(self):
        c = Cadence.WEEKLY
        self.assertFalse(c.is_due(1_000_000 - 2 * 86400, 1_000_000))
        self.assertTrue(c.is_due(1_000_000 - 8 * 86400, 1_000_000))

    def test_on_demand_never_scheduled(self):
        c = Cadence.ON_DEMAND
        self.assertFalse(c.scheduled)
        self.assertFalse(c.is_due(None, 1_000_000))

    def test_unknown_cadence_defaults_daily(self):
        self.assertIs(Cadence.from_name("nope"), Cadence.DAILY)

if __name__ == "__main__":
    unittest.main()
