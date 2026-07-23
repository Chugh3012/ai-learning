from __future__ import annotations

import json
import time

import numpy as np
from scipy.stats import spearmanr
from sklearn.metrics import ndcg_score

from prism.lib.config import FOUNDRY_DIR
from prism.lib.topics import DEFAULT_TOPIC, TopicPack, list_topics, load_pack
from prism.services.ranker import Ranker, BATCH

_RESULTS = FOUNDRY_DIR / "results"

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
            print("eval: FOUNDRY_PROJECT_ENDPOINT not set - skipping (treated as pass)")
            return 0
        worst = 0
        ran_any = False
        for topic_id in list_topics() or [DEFAULT_TOPIC]:
            pack = load_pack(topic_id)
            if not pack.golden.exists():
                print(f"eval[{topic_id}]: no golden set, skipping")
                continue
            ran_any = True
            worst = max(worst, self._run_topic(topic_id, pack))
        if not ran_any:
            print("eval: no topic has a golden set")
            return 1
        return worst

    def _run_topic(self, topic_id: str, pack: TopicPack) -> int:
        items = [json.loads(line) for line in pack.golden.read_text(encoding="utf-8").splitlines()
                 if line.strip()]
        thresholds = pack.thresholds
        samples = max(1, int(thresholds.get("samples", 3)))

        rows = [(it["id"], it["title"], it["summary"]) for it in items]
        samples_by_id: dict[int, list[float]] = {it["id"]: [] for it in items}
        for _ in range(samples):
            for start in range(0, len(rows), BATCH):
                for iid, sc in self.ranker.score_batch(rows[start:start + BATCH],
                                                       pack.rubric).items():
                    samples_by_id[iid].append(sc)
        scores = {iid: _median(v) if v else 0 for iid, v in samples_by_id.items()}

        # ponytail: spread = mean per-item score range across samples; 0 when samples=1 (no variance data)
        spread_vals = [max(v) - min(v) for v in samples_by_id.values() if len(v) > 1]
        spread = round(float(np.mean(spread_vals)) if spread_vals else 0.0, 1)

        scored = [dict(it, score=scores.get(it["id"], 0)) for it in items]
        metrics = {
            "spearman": round(_spearman([(it["score"], it["tier"]) for it in scored]), 3),
            "ndcg5": round(_ndcg_at(scored, 5), 3),
            "prec5": round(sum(1 for it in sorted(scored, key=lambda x: x["score"], reverse=True)[:5]
                               if it["tier"] >= 1) / 5, 3),
            "nonai_leak": max((it["score"] for it in scored if it.get("is_nonai")), default=0),
            "spread": spread,
        }
        _RESULTS.mkdir(parents=True, exist_ok=True)
        payload = {"topic": topic_id, "rubric_version": pack.rubric_version,
                   "model": self.ranker.model, "ts": int(time.time()),
                   "samples": samples, "metrics": metrics}
        (_RESULTS / f"gate_{topic_id}.json").write_text(json.dumps(payload, indent=2),
                                                        encoding="utf-8")
        (_RESULTS / "gate_latest.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")

        mins = thresholds.get("min", {})
        maxes = thresholds.get("max", {})
        leak_max = maxes.get("nonai_leak", 100)
        failures = []
        for key, floor in mins.items():
            if metrics.get(key, 0) < floor:
                failures.append(f"{key}={metrics.get(key)} < {floor}")
        for key, ceiling in maxes.items():
            if metrics.get(key, 0) > ceiling:
                failures.append(f"{key}={metrics.get(key)} > {ceiling}")

        print(f"eval[{topic_id}] ({self.ranker.model}, median-of-{samples}): "
              + "  ".join(f"{k}={v}" for k, v in metrics.items()))
        if failures:
            print(f"EVAL GATE FAILED [{topic_id}]: " + "; ".join(failures))
            return 1
        print(f"EVAL GATE PASSED [{topic_id}]")
        return 0
