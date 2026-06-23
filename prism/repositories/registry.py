from __future__ import annotations

from prism.domain.cadence import Cadence
from prism.domain.profile import Profile
from prism.domain.user import User

class UserRegistry:

    def __init__(self, users: list[User]):
        self._users = users

    @classmethod
    def from_subscribers(cls, account: str) -> "UserRegistry":
        # The subscribers table is the single registry of audiences: people (admin +
        # subscribers, email channel) and automation feeds (builder, digest channel, no
        # email). Graceful: no account / unreadable -> empty registry.
        from prism.repositories.subscribers import SubscriberStore
        reg = cls([])
        reg.add_subscribers(SubscriberStore(account).confirmed())
        return reg

    @property
    def users(self) -> list[User]:
        return self._users

    def add_subscribers(self, subs: list[dict]) -> int:
        # Each row becomes a distinct user. A row may carry an explicit `profiles` list (the
        # admin's curated feeds, or the builder's digest); otherwise we synthesize the default
        # daily email edition (which needs an address). The row's kind is the user's role.
        added = 0
        for s in subs:
            uid = str(s.get("user_id") or "")
            if not uid:
                continue
            email = str(s.get("email") or "")
            token = str(s.get("token") or "")
            raw = s.get("profiles")
            if raw:
                profiles = [Profile(
                    user_id=uid, id=str(p["id"]), channel=str(p.get("channel", "email")),
                    cadence=Cadence.from_name(str(p.get("cadence", "daily"))),
                    name=str(p.get("name", "")), top=int(p.get("top", 5)),
                    min_score=float(p.get("min_score", 0)), interest=str(p.get("interest", "")),
                    self_review=bool(p.get("self_review", False)), email=email,
                    unsubscribe_token=token, topic_id=str(p.get("topic_id", "ai")),
                ) for p in raw]
            elif email:
                profiles = [Profile(user_id=uid, id="prf_daily", channel="email",
                                    cadence=Cadence.DAILY, name="Daily edition", top=5,
                                    min_score=55, interest="", email=email,
                                    unsubscribe_token=token)]
            else:
                continue
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
