#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DIGESTS = ROOT / "digests"
BATCH = 25

def parse_digest(text: str) -> list[tuple[int, str, str]]:
    m = re.search(r"<!--\s*items:\s*([0-9,\s]+)-->", text)
    if not m:
        return []
    ids = [int(x) for x in m.group(1).split(",") if x.strip().isdigit()]
    blocks = re.findall(r"^\d+\.\s+(.+?)\n\s+(.+?)\n", text, re.MULTILINE)
    return [(i, t.strip(), s.strip()) for i, (t, s) in zip(ids, blocks)]

def _resolve_profile(role: str):
    try:
        sys.path.insert(0, str(ROOT))
        from ai_scout.repositories.registry import UserRegistry
        reg = UserRegistry.from_subscribers(os.environ.get("FEEDBACK_STORAGE", ""))
        return reg.profile_for_role(role)
    except Exception as e:
        print(f"review: could not resolve role '{role}' ({e})")
        return None

def judge(endpoint: str, model: str, interest: str,
          items: list[tuple[int, str, str]]) -> dict[int, bool]:
    if not (endpoint and items):
        return {}
    try:
        sys.path.insert(0, str(ROOT))
        from ai_scout.lib.foundry import openai_client, log_usage
        client = openai_client(endpoint)
    except Exception as e:
        print(f"review: client unavailable ({e})")
        return {}
    system = (
        "You are the builder of an AI/LLM pipeline, triaging your delivered digest for YOUR "
        f"interest:\n  {interest}\n"
        "For each item decide KEEP (genuinely worth your attention — a technique, release, or "
        "idea relevant to that interest you'd want to read or could apply) or SKIP (off-interest, "
        "generic, or noise). Be selective; most items are SKIP. Return ONLY JSON: "
        '{"v":[{"id":<int>,"k":<true|false>}, ...]} for every id.'
    )
    out: dict[int, bool] = {}
    for start in range(0, len(items), BATCH):
        batch = items[start:start + BATCH]
        listing = "\n".join(f"[{i}] {t[:160]} — {s[:300]}" for i, t, s in batch)
        try:
            resp = client.chat.completions.create(
                model=model, temperature=0, response_format={"type": "json_object"},
                messages=[{"role": "system", "content": system},
                          {"role": "user", "content": listing}], max_tokens=900)
            log_usage("review", resp)
            for v in json.loads(resp.choices[0].message.content).get("v", []):
                out[int(v["id"])] = bool(v["k"])
        except Exception as e:
            print(f"review: batch failed ({e})")
            break
    return out

def review(role: str, endpoint: str, model: str, account: str) -> int:
    prof = _resolve_profile(role)
    if prof is None:
        print(f"review: no profile for role '{role}'")
        return 0
    path = DIGESTS / f"{prof.filesafe_lens}-{datetime.now(timezone.utc):%Y-%m-%d}.md"
    if not path.exists():
        print(f"review: no digest for {prof.lens} today — nothing to react to")
        return 0
    items = parse_digest(path.read_text(encoding="utf-8"))
    verdicts = judge(endpoint, model, prof.interest, items)
    if not verdicts:
        return 0
    from outcome import record_votes
    keep = [i for i, k in verdicts.items() if k]
    skip = [i for i, k in verdicts.items() if not k]
    record_votes(account, prof.lens, keep, 1.0)
    record_votes(account, prof.lens, skip, -1.0)
    print(f"review: {prof.lens} kept {len(keep)}, skipped {len(skip)} of {len(items)} delivered")
    return len(verdicts)

def main() -> int:
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    role = sys.argv[1] if len(sys.argv) > 1 else "builder"
    review(role,
           os.environ.get("FOUNDRY_PROJECT_ENDPOINT", ""),
           os.environ.get("FOUNDRY_MODEL_NAME", "mini"),
           os.environ.get("FEEDBACK_STORAGE", ""))
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
