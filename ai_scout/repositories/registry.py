from __future__ import annotations

import json
from pathlib import Path

from ai_scout.domain.cadence import Cadence
from ai_scout.domain.profile import Profile
from ai_scout.domain.user import User
from ai_scout.lib.config import CONFIG_DIR

class UserRegistry:

    def __init__(self, users: list[User]):
        self._users = users

    @classmethod
    def load(cls, path: Path | None = None) -> "UserRegistry":
        data = json.loads((path or (CONFIG_DIR / "users.json")).read_text(encoding="utf-8"))
        return cls([User.from_dict(u) for u in data.get("users", [])])

    @property
    def users(self) -> list[User]:
        return self._users

    def add_subscribers(self, subs: list[dict]) -> int:
        # Each confirmed person becomes a real, distinct user. A row may carry an explicit
        # `profiles` list (e.g. the admin, with their curated feeds); otherwise we synthesize
        # the default daily edition. The row's kind ("subscriber" | "admin") is the user role.
        added = 0
        for s in subs:
            uid = str(s.get("user_id") or "")
            email = str(s.get("email") or "")
            if not (uid and email):
                continue
            raw = s.get("profiles")
            if raw:
                profiles = [Profile(
                    user_id=uid, id=str(p["id"]), channel=str(p.get("channel", "email")),
                    cadence=Cadence.from_name(str(p.get("cadence", "daily"))),
                    name=str(p.get("name", "")), top=int(p.get("top", 5)),
                    min_score=float(p.get("min_score", 0)), interest=str(p.get("interest", "")),
                    self_review=bool(p.get("self_review", False)), email=email,
                ) for p in raw]
            else:
                profiles = [Profile(user_id=uid, id="prf_daily", channel="email",
                                    cadence=Cadence.DAILY, name="Daily edition", top=5,
                                    min_score=55, interest="", email=email)]
            self._users.append(User(id=uid, name=str(s.get("name") or ""),
                                    role=str(s.get("kind") or "subscriber"), profiles=profiles))
            added += 1
        return added

    def profiles(self) -> list[Profile]:
        return [p for u in self._users for p in u.profiles]

    def user_by_role(self, role: str) -> User | None:
        return next((u for u in self._users if u.role == role), None)

    def profile_for_role(self, role: str) -> Profile | None:
        u = self.user_by_role(role)
        if not u or not u.profiles:
            return None
        return next((p for p in u.profiles if p.self_review), u.profiles[0])

    def find_profile(self, lens: str) -> Profile | None:
        return next((p for p in self.profiles() if p.lens == lens), None)

    def feedback_lenses(self) -> set[str]:
        return {p.lens for p in self.profiles() if p.channel in ("email", "digest")}
