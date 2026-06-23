from __future__ import annotations

import importlib

__version__ = "0.1.0"

# Curated public surface. Lazy so `import prism` stays cheap (no azure/openai/numpy
# pulled until a consumer actually touches a service).
_EXPORTS = {
    "Settings": "prism.lib.settings",
    "KnowledgeBase": "prism.repositories.knowledge",
    "BlobStore": "prism.repositories.blob",
    "FeedbackStore": "prism.repositories.feedback",
    "UserRegistry": "prism.repositories.registry",
    "Ingestor": "prism.services.ingest",
    "Ranker": "prism.services.ranker",
    "Embedder": "prism.services.embedder",
    "Selector": "prism.services.selector",
    "BriefBuilder": "prism.services.brief_builder",
    "FeedbackService": "prism.services.feedback_service",
    "SourceDiscoverer": "prism.services.discoverer",
    "Orchestrator": "prism.services.delivery.orchestrator",
}

__all__ = ["__version__", *sorted(_EXPORTS)]

def __getattr__(name: str):
    module = _EXPORTS.get(name)
    if module is None:
        raise AttributeError(f"module 'prism' has no attribute {name!r}")
    return getattr(importlib.import_module(module), name)

def __dir__():
    return sorted(__all__)
