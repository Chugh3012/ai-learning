#!/usr/bin/env python3
"""Maintainer review — the agent reacting to its delivered digest (keep/skip votes).

The maintainer is a USER: it judges the items in the digest it was delivered, exactly like a human
skimming their inbox and starring what's worth their attention. It reads ONLY the digest file
(agent/inbox.py downloaded it) — never the KB, never the engine. For each item it votes KEEP
(worth acting on) or SKIP (noise), recorded as a feedback gesture (outcome.record_votes) so the
daily feedback_ingest folds it into affinity:<lens>. Quiet day (no digest) -> no-op.

Idempotent by construction: votes upsert by (item, '<lens>:vote'), so re-reading the same digest
just rewrites the same verdict — no marker needed. The user is resolved by ROLE (never a hardcoded
id). Passwordless. Never raises fatally.

Usage:  python agent/review.py maintainer
"""
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
    """[(item_id, title, summary), ...] in delivery order, from a delivered digest markdown.

    The footer `<!-- items: a,b,c -->` is the position→id map; the Nth numbered block (title line
    + summary line) is the Nth id. Pairing by order keeps the agent oblivious to the KB."""
    m = re.search(r"<!--\s*items:\s*([0-9,\s]+)-->", text)
    if not m:
        return []
    ids = [int(x) for x in m.group(1).split(",") if x.strip().isdigit()]
    blocks = re.findall(r"^\d+\.\s+(.+?)\n\s+(.+?)\n", text, re.MULTILINE)
    return [(i, t.strip(), s.strip()) for i, (t, s) in zip(ids, blocks)]


def _resolve_profile(role: str):
    """Resolve the agent's delivery profile by USER ROLE (never a hardcoded id). Prefers a
    self_review profile, else the user's first. Returns a profiles.Profile or None."""
    try:
        sys.path.insert(0, str(ROOT / "tools"))
        from profiles import load_users, user_by_role
        u = user_by_role(load_users(), role)
        if not u or not u.profiles:
            return None
        return next((p for p in u.profiles if p.self_review), u.profiles[0])
    except Exception as e:  # noqa: BLE001
        print(f"review: could not resolve role '{role}' ({e})")
        return None


def judge(endpoint: str, model: str, interest: str,
          items: list[tuple[int, str, str]]) -> dict[int, bool]:
    """{item_id: keep?} — True = worth the user's attention, False = noise. No-op if unconfigured."""
    if not (endpoint and items):
        return {}
    try:
        sys.path.insert(0, str(ROOT / "tools"))
        from foundry import openai_client, log_usage
        client = openai_client(endpoint)
    except Exception as e:  # noqa: BLE001 — judging is optional; a quiet model means no votes
        print(f"review: client unavailable ({e})")
        return {}
    system = (
        "You are the maintainer of an AI/LLM pipeline, triaging your delivered digest for YOUR "
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
        except Exception as e:  # noqa: BLE001
            print(f"review: batch failed ({e})")
            break
    return out


def review(role: str, endpoint: str, model: str, account: str) -> int:
    """Vote keep/skip on today's delivered digest for the user with this ROLE. Returns votes
    cast (0 = no-op). Feedback is recorded against the profile's lens, exactly like a human click."""
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
    sys.path.insert(0, str(Path(__file__).resolve().parent))  # sibling 'outcome' import in CI
    role = sys.argv[1] if len(sys.argv) > 1 else "maintainer"
    review(role,
           os.environ.get("FOUNDRY_PROJECT_ENDPOINT", ""),
           os.environ.get("FOUNDRY_MODEL_NAME", "mini"),
           os.environ.get("FEEDBACK_STORAGE", ""))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
