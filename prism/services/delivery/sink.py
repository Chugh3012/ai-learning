from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

from prism.domain.profile import Profile
from prism.lib.settings import Settings
from prism.services.brief_builder import BriefBuilder
from prism.repositories.feedback import FeedbackStore
from prism.repositories.blob import BlobStore

@dataclass
class DeliveryContext:
    profile: Profile
    items: list
    settings: Settings
    brief_builder: BriefBuilder
    feedback_store: FeedbackStore
    blob: BlobStore | None = None

class Sink(ABC):

    @abstractmethod
    def deliver(self, ctx: DeliveryContext) -> bool:
        raise NotImplementedError
