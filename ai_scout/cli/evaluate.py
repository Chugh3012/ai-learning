from __future__ import annotations

import json
import os
import sys

from ai_scout.lib.config import CONFIG_DIR, FOUNDRY_DIR
from ai_scout.lib.metrics import Metrics
from ai_scout.lib.settings import Settings
from ai_scout.lib import foundry
from ai_scout.services.evaluator import RankEvaluator
from ai_scout.services.ranker import Ranker

def _in_ci() -> bool:
    return os.environ.get("GITHUB_ACTIONS") == "true" or bool(os.environ.get("CI"))

def required_config_missing(s: Settings) -> list[str]:
    # The eval gate is only meaningful if its inputs exist. Locally these may be absent
    # (dev convenience -> skip); in CI a missing one must FAIL, never silently pass.
    missing: list[str] = []
    if not s.foundry_project_endpoint:
        missing.append("FOUNDRY_PROJECT_ENDPOINT")
    if not s.foundry_model_name:
        missing.append("FOUNDRY_MODEL_NAME")
    if not (FOUNDRY_DIR / "datasets" / "golden_rank_v1.jsonl").exists():
        missing.append("golden_rank_v1.jsonl")
    if not (CONFIG_DIR / "eval.json").exists():
        missing.append("config/eval.json")
    return missing

def main() -> int:
    s = Settings()
    if _in_ci():
        missing = required_config_missing(s)
        if missing:
            print("EVAL GATE FAILED: missing required config in CI: " + ", ".join(missing))
            return 1
    code = RankEvaluator(Ranker(None, s.foundry_project_endpoint, s.foundry_model_name)).run()
    metrics = Metrics(s.metrics_dce, s.metrics_dcr_rule_id, s.metrics_stream)
    try:
        data = json.loads((FOUNDRY_DIR / "results" / "gate_latest.json").read_text(encoding="utf-8"))
        for k, v in data.get("metrics", {}).items():
            metrics.add(f"eval_{k}", v)
        metrics.add("eval_pass", 1 if code == 0 else 0)
        metrics.add("eval_cost_usd", foundry.cost_usd())
        metrics.flush()
    except Exception:
        pass
    return code

if __name__ == "__main__":
    sys.exit(main())
