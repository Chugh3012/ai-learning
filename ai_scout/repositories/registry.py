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

    def add_subscribers(self, subs: list[tuple[str, str, str]]) -> int:
        # Each confirmed newsletter subscriber becomes a real, distinct user with their
        # own daily email profile (own lens => own ranking, own feedback learning).
        added = 0
        for user_id, email, name in subs:
            if not (user_id and email):
                continue
            prof = Profile(user_id=user_id, id="prf_daily", channel="email",
                           cadence=Cadence.DAILY, name="Daily edition", top=5,
                           min_score=55, interest="", email=email)
            self._users.append(User(id=user_id, name=name, role="subscriber", profiles=[prof]))
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
