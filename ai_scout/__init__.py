"""ai-scout — layered AI/LLM scanning, ranking, and personalized delivery pipeline.

Layers (dependency direction is one-way: cli -> services -> repositories -> domain; lib is
cross-cutting):
  domain/        DTOs/entities (User, Profile, Cadence, Item, Brief) — pure data + behavior, no I/O
  repositories/  the only code that touches a store (KnowledgeBase, BlobStore, FeedbackStore, UserRegistry)
  services/      business logic, depends on repositories via constructor DI (Ranker, Selector, ...)
  lib/           cross-cutting pure utilities (foundry client, text, vectors, config/paths)
  cli/           thin entrypoints (argparse -> wire repos+services -> run)
The same services back a future FastAPI `api/` layer unchanged (constructor DI maps to Depends).
"""
