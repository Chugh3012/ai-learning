from __future__ import annotations

import json
import os
import sys

from prism.lib.config import FOUNDRY_DIR
from prism.lib.metrics import Metrics
from prism.lib.settings import Settings
from prism.lib import foundry
from prism.services.evaluator import RankEvaluator
from prism.services.ranker import Ranker

def _in_ci() -> bool:
    return os.environ.get("GITHUB_ACTIONS") == "true" or bool(os.environ.get("CI"))

def required_config_missing(s: Settings) -> list[str]:
    # The eval gate is only meaningful if its inputs exist. Locally these may be absent
    # (dev convenience -> skip); in CI a missing one must FAIL, never silently pass.
    from prism.lib.topics import list_topics, load_pack
    missing: list[str] = []
    if not s.foundry_project_endpoint:
        missing.append("FOUNDRY_PROJECT_ENDPOINT")
    if not s.foundry_model_name:
        missing.append("FOUNDRY_MODEL_NAME")
    topics = list_topics()
    if not topics:
        missing.append("topics/<id>/pack.json")
    elif not any(load_pack(t).golden.exists() and load_pack(t).rubric for t in topics):
        missing.append("a topic pack with rubric.txt + eval/golden.jsonl")
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
        from prism.lib.topics import list_topics
        for topic_id in list_topics():
            gate = FOUNDRY_DIR / "results" / f"gate_{topic_id}.json"
            if not gate.exists():
                continue
            data = json.loads(gate.read_text(encoding="utf-8"))
            for k, v in data.get("metrics", {}).items():
                metrics.add(f"eval_{k}", v, topic=topic_id)
        metrics.add("eval_pass", 1 if code == 0 else 0)
        metrics.add("eval_cost_usd", foundry.cost_usd())
        metrics.flush()
    except Exception:
        pass
    return code

if __name__ == "__main__":
    sys.exit(main())
