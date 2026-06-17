"""`python -m ai_scout.cli.evaluate` — the ranking eval gate (the CI merge authority).

Composition root: wires a Ranker (score-only) into the RankEvaluator and runs it. Exit 0 = pass.
"""
from __future__ import annotations

import sys

from ai_scout.lib.config import env_value
from ai_scout.services.evaluator import RankEvaluator
from ai_scout.services.ranker import Ranker


def main() -> int:
    endpoint = env_value("FOUNDRY_PROJECT_ENDPOINT")
    model = env_value("FOUNDRY_MODEL_NAME", "mini")
    return RankEvaluator(Ranker(None, endpoint, model)).run()


if __name__ == "__main__":
    sys.exit(main())
