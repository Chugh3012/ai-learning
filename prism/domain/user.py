from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from prism.domain.profile import Profile

class User(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str
    name: str = ""
    role: str = ""
    profiles: list[Profile] = []

    @property
    def label(self) -> str:
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
