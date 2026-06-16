#!/usr/bin/env python3
"""ai-scout ranking regression gate (P10) — runs the production rank prompt over a labeled
golden set and asserts quality thresholds, so a prompt/model change can't silently regress.

This is the Foundry `observe` methodology (labeled data + grader + thresholds) adapted to a
scoring task, since the eval MCP tooling targets deployed agents. Artifacts live under
.foundry/ : datasets/golden_rank_v1.jsonl (labeled) and results/ (run output).

Metrics (graded against hand labels):
  - spearman  : rank correlation of model score vs target tier (ordering quality)
  - ndcg@5    : are the top-5 the high-tier items?
  - prec@5    : fraction of top-5 that are on-topic (tier>=1)
  - nonai_leak: highest score given to a known NON-AI trap (gate health; lower is better)

Exit code 0 if all thresholds in config/eval.json pass, else 1 (fails the CI job).
Passwordless: Foundry via DefaultAzureCredential. Reads FOUNDRY_* from env/.env.
"""
from __future__ import annotations

import json
import math
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
DATASET = ROOT / ".foundry" / "datasets" / "golden_rank_v1.jsonl"
RESULTS = ROOT / ".foundry" / "results"
THRESHOLDS = ROOT / "config" / "eval.json"


def _env(key: str, default: str = "") -> str:
    if key in os.environ:
        return os.environ[key]
    envf = ROOT / ".env"
    if envf.exists():
        for line in envf.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and line.split("=", 1)[0].strip() == key:
                return line.split("=", 1)[1].strip()
    return default


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


def main() -> int:
    endpoint = _env("FOUNDRY_PROJECT_ENDPOINT")
    model = _env("FOUNDRY_MODEL_NAME", "mini")
    if not endpoint:
        print("eval: FOUNDRY_PROJECT_ENDPOINT not set — skipping (treated as pass)")
        return 0
    if not DATASET.exists():
        print(f"eval: golden set missing at {DATASET}")
        return 1

    items = [json.loads(line) for line in DATASET.read_text(encoding="utf-8").splitlines() if line.strip()]
    thresholds = json.loads(THRESHOLDS.read_text(encoding="utf-8")) if THRESHOLDS.exists() else {}

    from rank import _client, _score_batch, BATCH
    client = _client(endpoint)
    rows = [(it["id"], it["title"], it["summary"]) for it in items]
    scores: dict[int, int] = {}
    for start in range(0, len(rows), BATCH):
        scores.update(_score_batch(client, model, rows[start:start + BATCH]))

    scored = [dict(it, score=scores.get(it["id"], 0)) for it in items]
    metrics = {
        "spearman": round(_spearman([(it["score"], it["tier"]) for it in scored]), 3),
        "ndcg5": round(_ndcg_at(scored, 5), 3),
        "prec5": round(sum(1 for it in sorted(scored, key=lambda x: x["score"], reverse=True)[:5]
                           if it["tier"] >= 1) / 5, 3),
        "nonai_leak": max((it["score"] for it in scored if it["is_nonai"]), default=0),
    }
    RESULTS.mkdir(parents=True, exist_ok=True)
    (RESULTS / "gate_latest.json").write_text(
        json.dumps({"model": model, "ts": int(time.time()), "metrics": metrics}, indent=2),
        encoding="utf-8")

    # Gate: min thresholds for higher-is-better, max for leak.
    mins = thresholds.get("min", {})
    leak_max = thresholds.get("max", {}).get("nonai_leak", 100)
    failures = []
    for key, floor in mins.items():
        if metrics.get(key, 0) < floor:
            failures.append(f"{key}={metrics.get(key)} < {floor}")
    if metrics["nonai_leak"] > leak_max:
        failures.append(f"nonai_leak={metrics['nonai_leak']} > {leak_max}")

    print(f"eval ({model}): " + "  ".join(f"{k}={v}" for k, v in metrics.items()))
    if failures:
        print("EVAL GATE FAILED: " + "; ".join(failures))
        return 1
    print("EVAL GATE PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
