#!/usr/bin/env python3
"""ai-scout domain model — USERS, PROFILES, and delivery CADENCE.

A USER is an identity that owns one or more PROFILES. A PROFILE is one consumption mode:
a selection LENS (its `interest` sentence) + a delivery CHANNEL + thresholds + a CADENCE.

LENS is ALWAYS `<user>:<profile>` (no special cases). The bare `<user>` namespace is left
free for a future user-level shared interest. The lens namespaces every per-profile signal
(sent:<lens>, affinity:<lens>, fb_*:<lens>).

This module is pure config/domain logic — no DB, no Azure — so it is trivially testable.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

_USERS = Path(__file__).resolve().parent.parent / "config" / "users.json"


@dataclass(frozen=True)
class Cadence:
    """When a profile is DUE for delivery. `interval_days=None` => on-demand (never on the
    scheduled run; produced explicitly). Otherwise due when at least `interval_days` (minus a
    half-day of cron slack) have passed since the profile's last delivery."""
    name: str
    interval_days: float | None

    @property
    def scheduled(self) -> bool:
        """True if this cadence ever fires on the scheduled run (False for on-demand)."""
        return self.interval_days is not None

    def is_due(self, last_sent_ts: int | None, now: int) -> bool:
        if self.interval_days is None:
            return False
        if last_sent_ts is None:
            return True
        return (now - last_sent_ts) >= (self.interval_days - 0.5) * 86400


_CADENCES = {
    "daily": Cadence("daily", 1.0),
    "weekly": Cadence("weekly", 7.0),
    "on_demand": Cadence("on_demand", None),
}


def cadence(name: str) -> Cadence:
    """Resolve a cadence by name; unknown names fall back to daily."""
    return _CADENCES.get((name or "daily").strip(), _CADENCES["daily"])


@dataclass(frozen=True)
class Profile:
    """One consumption mode owned by a user. `id` is the IMMUTABLE identity (the lens key — never
    rename it or you orphan its signals); `name` is the mutable display label, free to change.
    `interest` is the selection lens (empty = pure shared relevance). `format` names a content
    recipe in config/content.yml (draft channel). `email_var` names the env/Actions var holding
    the address (email channel)."""
    user_id: str
    id: str
    channel: str
    cadence: Cadence
    name: str = ""
    top: int = 5
    min_score: float = 0.0
    interest: str = ""
    format: str | None = None
    email_var: str | None = None
    self_review: bool = False

    @property
    def lens(self) -> str:
        """The signal namespace AND CLI address for this profile: always `<user>:<profile.id>`,
        keyed on the IMMUTABLE id so the display `name` can change without orphaning signals."""
        return f"{self.user_id}:{self.id}"

    @property
    def label(self) -> str:
        """Human-facing label for headers/subjects; falls back to the id when unset."""
        return self.name or self.id

    @property
    def filesafe_lens(self) -> str:
        """The lens as a filesystem-safe token (the ':' becomes '-') for digest filenames."""
        return self.lens.replace(":", "-")


@dataclass(frozen=True)
class User:
    """An identity that owns profiles. `id` is an OPAQUE SURROGATE KEY (never renamed); `name` is
    the mutable display label; `role` is a capability tag ('owner', 'maintainer', ...) so code and
    workflows address a user by what it DOES, never by a hardcoded id."""
    id: str
    name: str = ""
    role: str = ""
    profiles: list[Profile] = field(default_factory=list)

    @property
    def label(self) -> str:
        """Human-facing label; falls back to the id when unset."""
        return self.name or self.id


def _to_profile(user_id: str, raw: dict) -> Profile:
    return Profile(
        user_id=user_id,
        id=str(raw["id"]),
        channel=str(raw.get("channel", "email")),
        cadence=cadence(str(raw.get("cadence", "daily"))),
        name=str(raw.get("name", "")),
        top=int(raw.get("top", 5)),
        min_score=float(raw.get("min_score", 0)),
        interest=str(raw.get("interest", "")),
        format=raw.get("format"),
        email_var=raw.get("email_var"),
        self_review=bool(raw.get("self_review", False)),
    )


def load_users(path: Path | None = None) -> list[User]:
    """Parse config/users.json into the domain model."""
    data = json.loads((path or _USERS).read_text(encoding="utf-8"))
    users: list[User] = []
    for u in data.get("users", []):
        uid = str(u["id"])
        users.append(User(
            id=uid,
            name=str(u.get("name", "")),
            role=str(u.get("role", "")),
            profiles=[_to_profile(uid, p) for p in u.get("profiles", [])],
        ))
    return users


def user_by_role(users: list[User], role: str) -> User | None:
    """Resolve a user by its capability role (e.g. 'maintainer') — so workflows/agents never
    hardcode an opaque user id."""
    return next((u for u in users if u.role == role), None)


def find_profile(users: list[User], lens: str) -> Profile | None:
    """Resolve a profile by its lens (`<user_id>:<profile_id>`)."""
    return next((p for u in users for p in u.profiles if p.lens == lens), None)


def all_profiles(users: list[User]) -> list[Profile]:
    """Flatten every user's profiles in declaration order."""
    return [p for u in users for p in u.profiles]


def feedback_lenses(users: list[User]) -> set[str]:
    """Lenses whose channel produces CLICK feedback (email/digest) — the only ones the feedback
    loop should reconcile. A 'draft' profile has no click loop, so its lens is excluded (else its
    delivered-but-never-clicked items would all age into false negatives)."""
    return {p.lens for u in users for p in u.profiles if p.channel in ("email", "digest")}
