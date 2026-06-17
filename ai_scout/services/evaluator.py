from __future__ import annotations

import json
import time

import numpy as np
from scipy.stats import spearmanr
from sklearn.metrics import ndcg_score

from ai_scout.lib.config import CONFIG_DIR, FOUNDRY_DIR
from ai_scout.services.ranker import Ranker, BATCH

_DATASET = FOUNDRY_DIR / "datasets" / "golden_rank_v1.jsonl"
_RESULTS = FOUNDRY_DIR / "results"
_THRESHOLDS = CONFIG_DIR / "eval.json"

def _spearman(pairs: list[tuple[float, float]]) -> float:
    if len(pairs) < 2:
        return 0.0
    rho = spearmanr([p[0] for p in pairs], [p[1] for p in pairs]).statistic
    return 0.0 if rho != rho else float(rho)

def _ndcg_at(scored: list[dict], k: int) -> float:
    if len(scored) < 2:
        return 0.0
    y_true = np.array([[2 ** it["tier"] - 1 for it in scored]], dtype=float)
    y_score = np.array([[it["score"] for it in scored]], dtype=float)
    return float(ndcg_score(y_true, y_score, k=k))

def _median(xs: list[float]) -> float:
    return float(np.median(xs))

class RankEvaluator:
    def __init__(self, ranker: Ranker):
        self.ranker = ranker

    def run(self) -> int:
        if not self.ranker.endpoint:
            print("eval: FOUNDRY_PROJECT_ENDPOINT not set — skipping (treated as pass)")
            return 0
        if not _DATASET.exists():
            print(f"eval: golden set missing at {_DATASET}")
            return 1
        items = [json.loads(line) for line in _DATASET.read_text(encoding="utf-8").splitlines()
                 if line.strip()]
        thresholds = json.loads(_THRESHOLDS.read_text(encoding="utf-8")) if _THRESHOLDS.exists() else {}
        samples = max(1, int(thresholds.get("samples", 3)))

        rows = [(it["id"], it["title"], it["summary"]) for it in items]
        samples_by_id: dict[int, list[float]] = {it["id"]: [] for it in items}
        for _ in range(samples):
            for start in range(0, len(rows), BATCH):
                for iid, sc in self.ranker.score_batch(rows[start:start + BATCH]).items():
                    samples_by_id[iid].append(sc)
        scores = {iid: _median(v) if v else 0 for iid, v in samples_by_id.items()}

        scored = [dict(it, score=scores.get(it["id"], 0)) for it in items]
        metrics = {
            "spearman": round(_spearman([(it["score"], it["tier"]) for it in scored]), 3),
            "ndcg5": round(_ndcg_at(scored, 5), 3),
            "prec5": round(sum(1 for it in sorted(scored, key=lambda x: x["score"], reverse=True)[:5]
                               if it["tier"] >= 1) / 5, 3),
            "nonai_leak": max((it["score"] for it in scored if it["is_nonai"]), default=0),
        }
        _RESULTS.mkdir(parents=True, exist_ok=True)
        (_RESULTS / "gate_latest.json").write_text(
            json.dumps({"model": self.ranker.model, "ts": int(time.time()), "samples": samples,
                        "metrics": metrics}, indent=2), encoding="utf-8")

        mins = thresholds.get("min", {})
        leak_max = thresholds.get("max", {}).get("nonai_leak", 100)
        failures = []
        for key, floor in mins.items():
            if metrics.get(key, 0) < floor:
                failures.append(f"{key}={metrics.get(key)} < {floor}")
        if metrics["nonai_leak"] > leak_max:
            failures.append(f"nonai_leak={metrics['nonai_leak']} > {leak_max}")

        print(f"eval ({self.ranker.model}, median-of-{samples}): "
              + "  ".join(f"{k}={v}" for k, v in metrics.items()))
        if failures:
            print("EVAL GATE FAILED: " + "; ".join(failures))
            return 1
        print("EVAL GATE PASSED")
        return 0
