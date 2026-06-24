from __future__ import annotations

import argparse
import datetime as dt
import sys
from pathlib import Path

from prism.lib.settings import Settings
from prism.lib.config import SCRATCH_DIR, KB_PATH
from prism.lib.gateway import ModelGateway
from prism.repositories.blob import BlobStore
from prism.repositories.knowledge import KnowledgeBase
from prism.services.selector import Selector
from prism.services.reel_script import ReelScripter
from reelforge import AzureSpeech, PexelsVisuals, Scene, Storyboard, Style, render

# A broadcast lens: the reel is a public "top AI updates" edition, not a personalized feed.
_LENS = "reel:broadcast"

def _parse_args(argv=None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(description="Render a vertical 'AI Radar' reel from the KB.")
    ap.add_argument("--top", type=int, default=5, help="how many items to feature")
    ap.add_argument("--topic", default="ai", help="topic pack id to pull from")
    ap.add_argument("--upload", action="store_true", help="upload the mp4 to Blob digests/reels/")
    ap.add_argument("--no-voice", action="store_true", help="skip the Azure Speech voiceover")
    ap.add_argument("--no-broll", action="store_true", help="skip Pexels b-roll (branded gradient)")
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

    # Script each item into a spoken line + a b-roll search query (graceful: raw title on failure).
    model = ModelGateway(s.foundry_project_endpoint, s.foundry_model_name).model_for("brief")
    hook, script = ReelScripter(s.foundry_project_endpoint, model).script(
        [(r.id, r.title, r.summary) for r in rows])

    n = len(rows)
    scenes = [Scene(kicker="AI RADAR", text=hook or "Today in AI",
                    query="artificial intelligence abstract technology")]
    for i, r in enumerate(rows, 1):
        _headline, line, query = (script.get(r.id, ("", "", "")) + ("", "", ""))[:3]
        scenes.append(Scene(kicker=f"{i:02d} / {n:02d}", text=line or r.title,
                            query=query or "technology abstract"))
    scenes.append(Scene(text="Follow for your daily AI signal.",
                        query="futuristic technology blue abstract"))

    tts = None
    if not args.no_voice and s.speech_resource_id:
        tts = AzureSpeech(resource_id=s.speech_resource_id, region=s.speech_region)
    visuals = None
    if not args.no_broll and s.pexels_api_key:
        visuals = PexelsVisuals(api_key=s.pexels_api_key)

    today = dt.date.today().isoformat()
    out = SCRATCH_DIR / "reels" / f"{today}.mp4"
    render(Storyboard(style=Style(caption_y=0.62), scenes=scenes), out, tts=tts, visuals=visuals)
    print(f"reel: wrote {out} ({out.stat().st_size} bytes, {n} items, "
          f"voice={'on' if tts else 'off'}, broll={'on' if visuals else 'off'})")

    if args.upload:
        ok = blob.put_file(f"digests/reels/{today}.mp4", out, content_type="video/mp4")
        print("reel: uploaded to Blob" if ok else "reel: STORAGE_ACCOUNT not set — skipped upload")
    return 0

if __name__ == "__main__":
    sys.exit(main())
