from __future__ import annotations

import enum

class Cadence(enum.Enum):
    DAILY = 1.0
    WEEKLY = 7.0
    ON_DEMAND = None

    @property
    def interval_days(self) -> float | None:
        return self.value

    @property
    def scheduled(self) -> bool:
        return self.value is not None

    def is_due(self, last_sent_ts: int | None, now: int) -> bool:
        if self.value is None:
            return False
        if last_sent_ts is None:
            return True
        return (now - last_sent_ts) >= (self.value - 0.5) * 86400

    @classmethod
    def from_name(cls, name: str) -> "Cadence":
        try:
            return cls[(name or "daily").strip().upper()]
        except KeyError:
            return cls.DAILY
