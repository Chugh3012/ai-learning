from __future__ import annotations

import sys

from ai_scout.lib.settings import Settings
from ai_scout.services.evaluator import RankEvaluator
from ai_scout.services.ranker import Ranker

def main() -> int:
    s = Settings()
    return RankEvaluator(Ranker(None, s.foundry_project_endpoint, s.foundry_model_name)).run()

if __name__ == "__main__":
    sys.exit(main())
