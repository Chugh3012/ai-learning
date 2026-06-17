"""Profile — one consumption mode owned by a user."""
from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from ai_scout.domain.cadence import Cadence


class Profile(BaseModel):
    """One consumption mode owned by a user. `id` is the IMMUTABLE identity (the lens key — never
    rename it or you orphan its signals); `name` is the mutable display label, free to change.
    `interest` is the selection lens (empty = pure shared relevance). `format` names a content
    recipe in config/content.yml (draft channel). `email_var` names the env/Actions var holding
    the address (email channel)."""
    model_config = ConfigDict(frozen=True)

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
            format=raw.get("format"),
            email_var=raw.get("email_var"),
            self_review=bool(raw.get("self_review", False)),
        )
