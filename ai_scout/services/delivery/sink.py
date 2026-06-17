"""Sink — the delivery-channel interface (port) + the context passed to it."""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

from ai_scout.domain.profile import Profile
from ai_scout.lib.settings import Settings
from ai_scout.services.brief_builder import BriefBuilder
from ai_scout.services.producer import ContentProducer
from ai_scout.repositories.feedback import FeedbackStore


@dataclass
class DeliveryContext:
    """Everything a sink needs to emit one profile's already-selected items (injected by the
    Orchestrator)."""
    profile: Profile
    items: list
    settings: Settings
    brief_builder: BriefBuilder
    feedback_store: FeedbackStore
    producer: ContentProducer


class Sink(ABC):
    """One output channel. `explore_ratio` None => the config default during selection; a content
    sink overrides to 0.0 (deterministic — never gamble a production slot on a wildcard)."""
    explore_ratio: float | None = None

    @abstractmethod
    def deliver(self, ctx: DeliveryContext) -> bool:
        """Emit the selected items. Return True on success (so the Orchestrator marks them sent)."""
        raise NotImplementedError
