"""Delivery cadence — when a profile is due."""
from __future__ import annotations

import enum


class Cadence(enum.Enum):
    """When a profile is DUE for delivery. The member VALUE is its interval in days (None =
    on-demand: never on the scheduled run, produced explicitly). A profile is due when at least
    `interval_days` (minus a half-day of cron slack) have passed since its last delivery."""
    DAILY = 1.0
    WEEKLY = 7.0
    ON_DEMAND = None

    @property
    def interval_days(self) -> float | None:
        return self.value

    @property
    def scheduled(self) -> bool:
        """True if this cadence ever fires on the scheduled run (False for on-demand)."""
        return self.value is not None

    def is_due(self, last_sent_ts: int | None, now: int) -> bool:
        if self.value is None:
            return False
        if last_sent_ts is None:
            return True
        return (now - last_sent_ts) >= (self.value - 0.5) * 86400

    @classmethod
    def from_name(cls, name: str) -> "Cadence":
        """Resolve a cadence by its config name (e.g. 'weekly'); unknown names fall back to daily."""
        try:
            return cls[(name or "daily").strip().upper()]
        except KeyError:
            return cls.DAILY
