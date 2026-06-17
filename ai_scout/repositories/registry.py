"""UserRegistry — loads the user/profile registry (config/users.json) into the domain model."""
from __future__ import annotations

import json
from pathlib import Path

from ai_scout.domain.profile import Profile
from ai_scout.domain.user import User
from ai_scout.lib.config import CONFIG_DIR


class UserRegistry:
    """The source of truth for who consumes the feed. Reads config/users.json once and answers
    look-ups by role / lens. Inject this anywhere a list of users/profiles is needed (DI)."""

    def __init__(self, users: list[User]):
        self._users = users

    @classmethod
    def load(cls, path: Path | None = None) -> "UserRegistry":
        data = json.loads((path or (CONFIG_DIR / "users.json")).read_text(encoding="utf-8"))
        return cls([User.from_dict(u) for u in data.get("users", [])])

    @property
    def users(self) -> list[User]:
        return self._users

    def profiles(self) -> list[Profile]:
        """Every user's profiles, in declaration order."""
        return [p for u in self._users for p in u.profiles]

    def user_by_role(self, role: str) -> User | None:
        """Resolve a user by capability role (e.g. 'maintainer') — never a hardcoded id."""
        return next((u for u in self._users if u.role == role), None)

    def profile_for_role(self, role: str) -> Profile | None:
        """The delivery profile of the user with this role (prefers a self_review profile)."""
        u = self.user_by_role(role)
        if not u or not u.profiles:
            return None
        return next((p for p in u.profiles if p.self_review), u.profiles[0])

    def find_profile(self, lens: str) -> Profile | None:
        """Resolve a profile by its lens (`<user_id>:<profile_id>`)."""
        return next((p for p in self.profiles() if p.lens == lens), None)

    def feedback_lenses(self) -> set[str]:
        """Lenses whose channel produces CLICK feedback (email/digest) — the only ones the feedback
        loop reconciles. A 'draft' profile has no click loop, so its lens is excluded (else its
        delivered-but-never-clicked items would all age into false negatives)."""
        return {p.lens for p in self.profiles() if p.channel in ("email", "digest")}
