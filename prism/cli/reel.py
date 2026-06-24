from __future__ import annotations

import argparse
import datetime as dt
import re
import sys
from pathlib import Path
from urllib.parse import urlparse

from prism.lib.settings import Settings
from prism.lib import text as textlib
from prism.lib.config import SCRATCH_DIR, KB_PATH
from prism.repositories.blob import BlobStore
from prism.lib.gateway import ModelGateway
from prism.repositories.knowledge import KnowledgeBase
from prism.services.selector import Selector
from prism.services.reel import ReelMaker
from prism.services.reel_script import ReelScripter

# A broadcast lens: the reel is a public "top AI updates" edition, not a personalized feed.
_LENS = "reel:broadcast"

def _takeaway(summary: str, limit: int = 160) -> str:
    s = textlib.clean(summary, limit + 200).strip()
    # arXiv summaries lead with "arXiv:NNNN Announce Type: ... Abstract:" boilerplate — drop it.
    s = re.sub(r"^arXiv:\S+.*?Abstract:\s*", "", s, flags=re.IGNORECASE).strip()
    if not s:
        return ""
    cut = s[:limit]
    dot = cut.rfind(". ")
    if dot >= 80:
        return cut[: dot + 1]
    sp = cut.rfind(" ")
    return (cut[:sp] if sp >= 80 else cut).rstrip(" ,;:") + ("..." if len(s) > limit else "")

def _source(url: str) -> str:
    return (urlparse(url).hostname or "").removeprefix("www.")

def _parse_args(argv=None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(description="Render a vertical 'AI radar' update video from the KB.")
    ap.add_argument("--top", type=int, default=5, help="how many items to feature")
    ap.add_argument("--topic", default="ai", help="topic pack id to pull from")
    ap.add_argument("--seconds", type=float, default=3.5, help="seconds per card")
    ap.add_argument("--upload", action="store_true", help="upload the mp4 to Blob digests/reels/")
    ap.add_argument("--no-script", action="store_true",
                    help="skip the LLM rewrite; use raw KB title/summary on the cards")
    return ap.parse_args(argv)

def main(argv=None) -> int:
    args = _parse_args(argv)
    s = Settings()

    blob = BlobStore(s.storage_account)
    if blob.enabled and not Path(KB_PATH).exists():
        blob.download_kb()

    kb = KnowledgeBase.open()
    rows = Selector(kb).select(_LENS, top=args.top, topic_id=args.topic)
    if not rows:
        print("reel: no items to feature — nothing rendered")
        return 0

    # LLM script pass: rewrite each item into a punchy headline + one crisp line. Graceful —
    # falls back to the raw KB title/summary when the model is unconfigured or fails.
    hook, script = "", {}
    if not args.no_script:
        model = ModelGateway(s.foundry_project_endpoint, s.foundry_model_name).model_for("brief")
        hook, script = ReelScripter(s.foundry_project_endpoint, model).script(
            [(r.id, r.title, r.summary) for r in rows])

    items = []
    for r in rows:
        headline, line = script.get(r.id, ("", ""))
        items.append({"headline": headline or r.title,
                      "takeaway": line or _takeaway(r.summary),
                      "source": _source(r.url)})
    today = dt.date.today().isoformat()
    out = SCRATCH_DIR / "reels" / f"{today}.mp4"
    ReelMaker(seconds_per_card=args.seconds).build(
        items, out, title=hook or "Today in AI", outro="follow for daily AI signal")
    print(f"reel: wrote {out} ({out.stat().st_size} bytes, {len(items)} items)")

    if args.upload:
        ok = blob.put_file(f"digests/reels/{today}.mp4", out, content_type="video/mp4")
        print("reel: uploaded to Blob" if ok else "reel: STORAGE_ACCOUNT not set — skipped upload")
    return 0

if __name__ == "__main__":
    sys.exit(main())
