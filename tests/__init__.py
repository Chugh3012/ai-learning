"""Offline unit tests for ai-scout's deterministic core (no Azure, no network).

These guard the pure logic the LLM eval gate can't: curation, feedback/affinity math, the
two-tower embedding math, and the personalization selection path. Run with `python -m
unittest discover tests` — wired into pr-gate.yml so a logic regression blocks merge the same
way an eval regression does. Uses only stdlib (unittest + sqlite :memory:).
"""
