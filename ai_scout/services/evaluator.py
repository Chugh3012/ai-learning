"""RankEvaluator — the ranking regression gate: runs the production rank prompt over a labeled
golden set (median-of-N) and asserts quality thresholds, so a prompt/model change can't silently
regress. Depends on a Ranker (DI). Metrics: spearman, ndcg@5, prec@5, nonai_leak.
"""
from __future__ import annotations

import json
import math
import time

from ai_scout.lib.config import CONFIG_DIR, FOUNDRY_DIR
from ai_scout.services.ranker import Ranker, BATCH

_DATASET = FOUNDRY_DIR / "datasets" / "golden_rank_v1.jsonl"
_RESULTS = FOUNDRY_DIR / "results"
_THRESHOLDS = CONFIG_DIR / "eval.json"


def _spearman(pairs: list[tuple[float, float]]) -> float:
    n = len(pairs)
    if n < 2:
        return 0.0

    def ranks(vals: list[float]) -> list[float]:
        order = sorted(range(n), key=lambda i: vals[i])
        r = [0.0] * n
        i = 0
        while i < n:
            j = i
            while j + 1 < n and vals[order[j + 1]] == vals[order[i]]:
                j += 1
            for k in range(i, j + 1):
                r[order[k]] = (i + j) / 2 + 1
            i = j + 1
        return r

    rs, rt = ranks([p[0] for p in pairs]), ranks([p[1] for p in pairs])
    mrs, mrt = sum(rs) / n, sum(rt) / n
    cov = sum((rs[i] - mrs) * (rt[i] - mrt) for i in range(n))
    vs = sum((rs[i] - mrs) ** 2 for i in range(n)) ** 0.5
    vt = sum((rt[i] - mrt) ** 2 for i in range(n)) ** 0.5
    return cov / (vs * vt) if vs and vt else 0.0


def _ndcg_at(scored: list[dict], k: int) -> float:
    srt = sorted(scored, key=lambda it: it["score"], reverse=True)
    dcg = sum((2 ** it["tier"] - 1) / math.log2(i + 2) for i, it in enumerate(srt[:k]))
    ideal = sorted(scored, key=lambda it: it["tier"], reverse=True)
    idcg = sum((2 ** it["tier"] - 1) / math.log2(i + 2) for i, it in enumerate(ideal[:k]))
    return dcg / idcg if idcg else 0.0


def _median(xs: list[float]) -> float:
    s = sorted(xs)
    n = len(s)
    return s[n // 2] if n % 2 else (s[n // 2 - 1] + s[n // 2]) / 2


class RankEvaluator:
    def __init__(self, ranker: Ranker):
        self.ranker = ranker

    def run(self) -> int:
        """Score the golden set median-of-N, write results, and return 0 (pass) / 1 (fail)."""
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
