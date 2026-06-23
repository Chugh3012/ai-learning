from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from prism.domain.cadence import Cadence

class Profile(BaseModel):
    model_config = ConfigDict(frozen=True)

    user_id: str
    id: str
    channel: str
    cadence: Cadence
    name: str = ""
    top: int = 5
    min_score: float = 0.0
    interest: str = ""
    email_var: str | None = None
    email: str = ""
    unsubscribe_token: str = ""
    self_review: bool = False
    topic_id: str = "ai"

    @property
    def lens(self) -> str:
        return f"{self.user_id}:{self.id}"

    @property
    def label(self) -> str:
        return self.name or self.id

    @property
    def filesafe_lens(self) -> str:
        return self.lens.replace(":", "-")

    @classmethod
    def from_dict(cls, user_id: str, raw: dict) -> "Profile":
        return cls(
            user_id=user_id,
            id=str(raw["id"]),
            channel=str(raw.get("channel", "email")),
            cadence=Cadence.from_name(str(raw.get("cadence", "daily"))),
            name=str(raw.get("name", "")),
            top=int(raw.get("top", 5)),
            min_score=float(raw.get("min_score", 0)),
            interest=str(raw.get("interest", "")),
            email_var=raw.get("email_var"),
            email=str(raw.get("email", "")),
            unsubscribe_token=str(raw.get("unsubscribe_token", "")),
            self_review=bool(raw.get("self_review", False)),
            topic_id=str(raw.get("topic_id", "ai")),
        )
