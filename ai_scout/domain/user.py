"""User — an identity that owns profiles."""
from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from ai_scout.domain.profile import Profile


class User(BaseModel):
    """An identity that owns profiles. `id` is an OPAQUE SURROGATE KEY (never renamed); `name` is
    the mutable display label; `role` is a capability tag ('owner', 'maintainer', ...) so code and
    workflows address a user by what it DOES, never by a hardcoded id."""
    model_config = ConfigDict(frozen=True)

    id: str
    name: str = ""
    role: str = ""
    profiles: list[Profile] = []

    @property
    def label(self) -> str:
        """Human-facing label; falls back to the id when unset."""
        return self.name or self.id

    @classmethod
    def from_dict(cls, raw: dict) -> "User":
        uid = str(raw["id"])
        return cls(
            id=uid,
            name=str(raw.get("name", "")),
            role=str(raw.get("role", "")),
            profiles=[Profile.from_dict(uid, p) for p in raw.get("profiles", [])],
        )

