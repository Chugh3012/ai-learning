from __future__ import annotations

import argparse
import datetime as dt
import sys
from pathlib import Path

from prism.lib.settings import Settings
from prism.lib.config import SCRATCH_DIR, KB_PATH, config_json
from prism.lib.gateway import ModelGateway
from prism.lib.text import fulltext
from prism.repositories.blob import BlobStore
from prism.repositories.knowledge import KnowledgeBase
from prism.services.embedder import Embedder
from prism.services.selector import Selector
from prism.services.reel_script import ReelScripter
from reelforge import AzureSpeech, PexelsVisuals, Scene, Storyboard, Style, render

# A broadcast lens: the reel is a public "top AI updates" edition, not a personalized feed. Its
# relevance is steered by config/reel.json (interest sentence) so it surfaces catchy, concrete
# stories rather than dry academic papers.
_LENS = "reel:broadcast"
_INTRO_Q = "artificial intelligence abstract technology"
_OUTRO_Q = "futuristic technology blue abstract"

def _parse_args(argv=None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(description="Render a vertical 'AI Radar' reel from the KB.")
    ap.add_argument("--mode", choices=["roundup", "deep"], default="roundup",
                    help="roundup = several stories in one reel; deep = one story, explained")
    ap.add_argument("--count", type=int, default=5, help="stories to feature in roundup mode")
    ap.add_argument("--topic", default="ai", help="topic pack id to pull from")
    ap.add_argument("--upload", action="store_true", help="upload the mp4 to Blob digests/reels/")
    ap.add_argument("--no-voice", action="store_true", help="skip the Azure Speech voiceover")
    ap.add_argument("--no-broll", action="store_true", help="skip Pexels b-roll (branded gradient)")
    return ap.parse_args(argv)

def main(argv=None) -> int:
    args = _parse_args(argv)
    s = Settings()
    cfg = config_json("reel.json")

    blob = BlobStore(s.storage_account)
    if blob.enabled and not Path(KB_PATH).exists():
        blob.download_kb()

    kb = KnowledgeBase.open()
    gateway = ModelGateway(s.foundry_project_endpoint, s.foundry_model_name)
    scripter = ReelScripter(s.foundry_project_endpoint, gateway.model_for("brief"))

    # Steer selection toward catchy, concrete stories via the configured interest sentence.
    interest_vec = Embedder(kb, s.foundry_project_endpoint, gateway.model_for("embed")).embed_interest(
        cfg.get("interest", ""))
    weight = float(cfg.get("interest_weight", 20))
    want = max(args.count, 8) if args.mode == "roundup" else 8
    pool = Selector(kb).select(_LENS, want, 0.0, interest_vec, weight, None, args.topic)
    if not pool:
        print("reel: no items to feature — nothing rendered")
        return 0

    if args.mode == "deep":
        scenes, label = _deep_scenes(pool[0], scripter), "deep"
    else:
        scenes, label = _roundup_scenes(pool[: args.count], scripter), "roundup"

    tts = None
    if not args.no_voice and s.speech_resource_id:
        tts = AzureSpeech(resource_id=s.speech_resource_id, region=s.speech_region,
                          voice=cfg.get("voice", "en-US-AvaMultilingualNeural"))
    visuals = None
    if not args.no_broll and s.pexels_api_key:
        visuals = PexelsVisuals(api_key=s.pexels_api_key)

    style = Style(caption_y=0.62, words_per_chunk=int(cfg.get("words_per_chunk", 3)))
    name = f"{dt.date.today().isoformat()}-{label}.mp4"
    out = SCRATCH_DIR / "reels" / name
    render(Storyboard(style=style, scenes=scenes), out, tts=tts, visuals=visuals)
    print(f"reel: wrote {out} ({out.stat().st_size} bytes, {len(scenes)} scenes, mode={label}, "
          f"voice={'on' if tts else 'off'}, broll={'on' if visuals else 'off'})")

    uploaded = bool(args.upload and blob.put_file(f"digests/reels/{name}", out, "video/mp4"))
    print("\nDOWNLOAD:")
    print(f"  local: {out.resolve()}")
    if uploaded:
        print(f"  blob:  {s.storage_account}/{s.blob_container}/digests/reels/{name}")
        print(f"  az storage blob download --account-name {s.storage_account} --container-name "
              f"{s.blob_container} --name digests/reels/{name} --file {name} --auth-mode login")
    return 0

def _roundup_scenes(rows: list, scripter: ReelScripter) -> list[Scene]:
    hook, script = scripter.script([(r.id, r.title, r.summary) for r in rows])
    n = len(rows)
    scenes = [Scene(kicker="AI RADAR", text=hook or "Today in AI", query=_INTRO_Q)]
    for i, r in enumerate(rows, 1):
        _headline, line, query = (script.get(r.id, ("", "", "")) + ("", "", ""))[:3]
        scenes.append(Scene(kicker=f"{i:02d} / {n:02d}", text=line or r.title,
                            query=query or "technology abstract"))
    scenes.append(Scene(text="Follow for your daily AI signal.", query=_OUTRO_Q))
    return scenes

def _deep_scenes(row, scripter: ReelScripter) -> list[Scene]:
    body = fulltext(row.url) or row.summary
    hook, beats = scripter.script_deep(row.title, body)
    scenes = [Scene(kicker="AI RADAR", text=hook or row.title, query=_INTRO_Q)]
    total = len(beats)
    for i, (text, query) in enumerate(beats, 1):
        scenes.append(Scene(kicker=f"{i:02d} / {total:02d}", text=text,
                            query=query or "technology abstract"))
    scenes.append(Scene(text="Follow for your daily AI signal.", query=_OUTRO_Q))
    return scenes

if __name__ == "__main__":
    sys.exit(main())
