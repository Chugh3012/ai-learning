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
    profile: Profile
    items: list
    settings: Settings
    brief_builder: BriefBuilder
    feedback_store: FeedbackStore
    producer: ContentProducer

class Sink(ABC):
    explore_ratio: float | None = None

    @abstractmethod
    def deliver(self, ctx: DeliveryContext) -> bool:
        raise NotImplementedError
