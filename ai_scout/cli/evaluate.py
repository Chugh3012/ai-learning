from __future__ import annotations

import json
import sys

from ai_scout.lib.config import FOUNDRY_DIR
from ai_scout.lib.metrics import Metrics
from ai_scout.lib.settings import Settings
from ai_scout.services.evaluator import RankEvaluator
from ai_scout.services.ranker import Ranker

def main() -> int:
    s = Settings()
    code = RankEvaluator(Ranker(None, s.foundry_project_endpoint, s.foundry_model_name)).run()
    metrics = Metrics(s.metrics_dce, s.metrics_dcr_rule_id, s.metrics_stream)
    try:
        data = json.loads((FOUNDRY_DIR / "results" / "gate_latest.json").read_text(encoding="utf-8"))
        for k, v in data.get("metrics", {}).items():
            metrics.add(f"eval_{k}", v)
        metrics.add("eval_pass", 1 if code == 0 else 0)
        metrics.flush()
    except Exception:
        pass
    return code

if __name__ == "__main__":
    sys.exit(main())
