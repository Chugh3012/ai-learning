#!/usr/bin/env python3
"""ai-scout feedback → fine-tuning dataset exporter (future-facing, opt-in).

The feedback loop (P7) already stores every gesture as a KB signal linked to the item's
text and relevance score. That is exactly the raw material for model customization later:
  - SFT/relevance: (item text) -> (a score the user implicitly endorsed)
  - DPO/preference: (👍 item) is "chosen" over a (👎 item) — a preference pair

This exporter turns that KB feedback into a training file ON DEMAND, so when enough signal
has accumulated, fine-tuning is a `python tools/feedback_export.py` away — not a rebuild.
We do NOT fine-tune yet: preference tuning needs a few hundred labeled examples to beat a
good prompt, and the loop is new. Until then the cheap additive-affinity personalization
(P7) carries it. See MIN_PAIRS below for the go/no-go gate.

Usage:
  python tools/feedback_export.py --format dpo   # preference pairs (👍 over 👎)
  python tools/feedback_export.py --format sft   # (item -> endorsed score) rows
Writes to .foundry/datasets/. Read-only on the KB.
"""
from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
KB = ROOT / "data" / "kb" / "kb.sqlite"
OUT_DIR = ROOT / ".foundry" / "datasets"
# Don't bother fine-tuning below this many usable examples — prompt will win.
MIN_PAIRS = 200


def _voted(con: sqlite3.Connection, want: float) -> list[tuple[int, str, str]]:
    """Items whose net vote signal matches sign(want): +1 = upvoted, -1 = downvoted."""
    op = ">" if want > 0 else "<"
    return con.execute(
        f"SELECT i.id, i.title, i.summary FROM item i "
        f"JOIN (SELECT item_id, SUM(value) v FROM signal WHERE kind='fb_vote' GROUP BY item_id) f "
        f"ON f.item_id=i.id WHERE f.v {op} 0",
        (),
    ).fetchall()


def export_dpo(con: sqlite3.Connection) -> Path:
    """Preference pairs: each 👍 item is 'chosen' vs each 👎 item 'rejected' (capped)."""
    up = _voted(con, +1)
    down = _voted(con, -1)
    pairs = []
    for u in up:
        for d in down[:5]:  # cap fan-out to keep the set balanced
            pairs.append({
                "input": {"messages": [{"role": "user",
                          "content": "Which item is a more practical, new way to USE AI/LLMs?"}]},
                "preferred_output": [{"role": "assistant", "content": f"{u[1]} — {(u[2] or '')[:300]}"}],
                "non_preferred_output": [{"role": "assistant", "content": f"{d[1]} — {(d[2] or '')[:300]}"}],
            })
    out = OUT_DIR / "feedback_dpo.jsonl"
    out.write_text("\n".join(json.dumps(p) for p in pairs), encoding="utf-8")
    print(f"dpo: {len(up)} up x {len(down)} down -> {len(pairs)} pairs -> {out}")
    if len(pairs) < MIN_PAIRS:
        print(f"NOTE: {len(pairs)} pairs < {MIN_PAIRS} — keep using additive-affinity (P7); "
              f"don't fine-tune yet.")
    return out


def export_sft(con: sqlite3.Connection) -> Path:
    """SFT rows: (item text) -> the relevance score, biased by the user's vote. A future
    distillation target if we want the model to internalize the user's taste."""
    rows = con.execute(
        "SELECT i.title, i.summary, "
        "  (SELECT value FROM signal r WHERE r.item_id=i.id AND r.kind='relevance') AS rel, "
        "  (SELECT SUM(value) FROM signal v WHERE v.item_id=i.id AND v.kind='fb_vote') AS vote "
        "FROM item i WHERE EXISTS "
        "  (SELECT 1 FROM signal s WHERE s.item_id=i.id AND s.kind='fb_vote')"
    ).fetchall()
    recs = []
    for title, summary, rel, vote in rows:
        base = rel if rel is not None else 50
        adj = max(0, min(100, int(base + 15 * (vote or 0))))  # nudge toward the user's vote
        recs.append({"messages": [
            {"role": "user", "content": f"Rate 0-100 how practical/new this AI item is:\n{title}\n{(summary or '')[:300]}"},
            {"role": "assistant", "content": str(adj)},
        ]})
    out = OUT_DIR / "feedback_sft.jsonl"
    out.write_text("\n".join(json.dumps(r) for r in recs), encoding="utf-8")
    print(f"sft: {len(recs)} rows -> {out}")
    if len(recs) < MIN_PAIRS:
        print(f"NOTE: {len(recs)} rows < {MIN_PAIRS} — not enough to fine-tune yet.")
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--format", choices=["dpo", "sft"], default="dpo")
    args = ap.parse_args()
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(KB)
    try:
        (export_dpo if args.format == "dpo" else export_sft)(con)
    finally:
        con.close()
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
