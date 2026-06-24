from __future__ import annotations

import re
from dataclasses import dataclass, field


@dataclass(frozen=True)
class Edition:
    """The typed hand-off between the producer (kb-sync) and any consumer (email, builder, reel):
    the ranked items selected for a lens on a date. It OWNS its own on-disk form — the
    `<!-- items: ... -->` footer carried by every digest — so no consumer ever parses markdown by
    hand. Details (title/url/…) are resolved from the store by id; this stays a thin, typed handle."""

    lens: str
    ids: list[int] = field(default_factory=list)

    _FOOTER = re.compile(r"<!--\s*items:\s*([\d,\s]+?)\s*-->")

    def footer(self) -> str:
        return f"<!-- items: {','.join(str(i) for i in self.ids)} -->"

    @classmethod
    def from_markdown(cls, lens: str, md: str) -> "Edition":
        m = cls._FOOTER.search(md or "")
        ids = [int(x) for x in m.group(1).split(",") if x.strip().isdigit()] if m else []
        return cls(lens=lens, ids=ids)
