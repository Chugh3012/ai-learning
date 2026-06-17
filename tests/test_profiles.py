"""profiles — domain model: surrogate ids, role resolution, cadence, lens helpers (offline)."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))
import profiles  # noqa: E402


class TestRegistry(unittest.TestCase):
    def setUp(self):
        self.users = profiles.load_users()

    def test_users_have_opaque_ids_and_roles(self):
        roles = {u.role for u in self.users}
        self.assertIn("owner", roles)
        self.assertIn("maintainer", roles)
        for u in self.users:
            self.assertTrue(u.id.startswith("usr_"))      # surrogate prefix
            for p in u.profiles:
                self.assertTrue(p.id.startswith("prf_"))

    def test_user_by_role(self):
        m = profiles.user_by_role(self.users, "maintainer")
        self.assertIsNotNone(m)
        self.assertEqual(m.role, "maintainer")
        self.assertIsNone(profiles.user_by_role(self.users, "nobody"))

    def test_lens_is_composite_and_filesafe(self):
        p = self.users[0].profiles[0]
        self.assertEqual(p.lens, f"{self.users[0].id}:{p.id}")
        self.assertEqual(p.filesafe_lens, p.lens.replace(":", "-"))
        self.assertNotIn(":", p.filesafe_lens)

    def test_find_profile_by_lens(self):
        p0 = profiles.all_profiles(self.users)[0]
        self.assertIs(profiles.find_profile(self.users, p0.lens), p0)
        self.assertIsNone(profiles.find_profile(self.users, "usr_x:prf_y"))

    def test_feedback_lenses_excludes_draft(self):
        fl = profiles.feedback_lenses(self.users)
        for u in self.users:
            for p in u.profiles:
                if p.channel == "draft":
                    self.assertNotIn(p.lens, fl)     # draft has no click loop
                else:
                    self.assertIn(p.lens, fl)


class TestCadence(unittest.TestCase):
    def test_daily_due_when_never_sent_or_old(self):
        c = profiles.Cadence.DAILY
        self.assertTrue(c.scheduled)
        self.assertTrue(c.is_due(None, 1_000_000))             # never sent
        self.assertTrue(c.is_due(1_000_000 - 2 * 86400, 1_000_000))

    def test_weekly_holds_until_interval(self):
        c = profiles.Cadence.WEEKLY
        self.assertFalse(c.is_due(1_000_000 - 2 * 86400, 1_000_000))   # 2d < 7d
        self.assertTrue(c.is_due(1_000_000 - 8 * 86400, 1_000_000))    # 8d >= 7d

    def test_on_demand_never_scheduled(self):
        c = profiles.Cadence.ON_DEMAND
        self.assertFalse(c.scheduled)
        self.assertFalse(c.is_due(None, 1_000_000))

    def test_unknown_cadence_defaults_daily(self):
        self.assertIs(profiles.Cadence.from_name("nope"), profiles.Cadence.DAILY)


if __name__ == "__main__":
    unittest.main()
