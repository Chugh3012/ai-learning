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
from prism.services.reel_playbook import Playbook, load_playbook
from reelforge import (AzureSpeech, PexelsVisuals, Scene, Storyboard, Style, bundled_music,
                       render)

# A broadcast lens: the reel is a public "top AI updates" edition, not a personalized feed. Its
# relevance is steered by config/reel.json (interest sentence) so it surfaces catchy, concrete
# stories rather than dry academic papers. The creative theory (hooks, structure, pacing) lives in
# a swappable playbook (config/playbooks/<name>.json) — edit/add one to experiment, no code change.
_LENS = "reel:broadcast"

def _parse_args(argv=None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(description="Render a vertical 'AI Radar' reel from the KB.")
    ap.add_argument("--mode", choices=["roundup", "deep"], default="roundup",
                    help="roundup = several stories in one reel; deep = one story, explained")
    ap.add_argument("--count", type=int, default=5, help="stories to feature in roundup mode")
    ap.add_argument("--topic", default="ai", help="topic pack id to pull from")
    ap.add_argument("--playbook", default="", help="creative playbook name (config/playbooks/<name>.json)")
    ap.add_argument("--upload", action="store_true", help="upload the mp4 to Blob digests/reels/")
    ap.add_argument("--no-voice", action="store_true", help="skip the Azure Speech voiceover")
    ap.add_argument("--no-broll", action="store_true", help="skip Pexels b-roll (branded gradient)")
    ap.add_argument("--no-music", action="store_true", help="skip the background music bed")
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
    playbook = load_playbook(args.playbook or cfg.get("playbook", "explainer"))

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
        scenes, label = _deep_scenes(pool[0], scripter, playbook), "deep"
    else:
        scenes, label = _roundup_scenes(pool[: args.count], scripter, playbook), "roundup"

    tts = None
    if not args.no_voice and s.speech_resource_id:
        tts = AzureSpeech(resource_id=s.speech_resource_id, region=s.speech_region,
                          voice=cfg.get("voice", "en-US-AvaMultilingualNeural"),
                          style=cfg.get("voice_style", ""), rate=cfg.get("voice_rate", ""))
    visuals = None
    if not args.no_broll and s.pexels_api_key:
        visuals = PexelsVisuals(api_key=s.pexels_api_key)
    music = "" if args.no_music else (cfg.get("music") or bundled_music())

    base_style = {"caption_y": 0.62, "words_per_chunk": int(cfg.get("words_per_chunk", 3))}
    style = Style(**{**base_style, **playbook.style})
    name = f"{dt.date.today().isoformat()}-{label}.mp4"
    out = SCRATCH_DIR / "reels" / name
    render(Storyboard(style=style, scenes=scenes, music=music), out, tts=tts, visuals=visuals)
    print(f"reel: wrote {out} ({out.stat().st_size} bytes, {len(scenes)} scenes, mode={label}, "
          f"voice={'on' if tts else 'off'}, broll={'on' if visuals else 'off'}, "
          f"music={'on' if music else 'off'})")

    uploaded = bool(args.upload and blob.put_file(f"digests/reels/{name}", out, "video/mp4"))
    print("\nDOWNLOAD:")
    print(f"  local: {out.resolve()}")
    if uploaded:
        print(f"  blob:  {s.storage_account}/{s.blob_container}/digests/reels/{name}")
        print(f"  az storage blob download --account-name {s.storage_account} --container-name "
              f"{s.blob_container} --name digests/reels/{name} --file {name} --auth-mode login")
    return 0

def _roundup_scenes(rows: list, scripter: ReelScripter, pb: Playbook) -> list[Scene]:
    # No top numbering (distracting); the opener is the hook phrase, then one card per story.
    hook, script = scripter.script([(r.id, r.title, r.summary) for r in rows], pb.roundup_system)
    scenes = [Scene(text=hook or "Today in AI", query=pb.intro_query)]
    for r in rows:
        _headline, line, query = (script.get(r.id, ("", "", "")) + ("", "", ""))[:3]
        scenes.append(Scene(text=line or r.title, query=query or "technology abstract"))
    scenes.append(Scene(text=pb.cta, query=pb.outro_query))
    return scenes

def _deep_scenes(row, scripter: ReelScripter, pb: Playbook) -> list[Scene]:
    # Hook-first: the very first scene IS the spoken hook (beat 1) — no separate title card, no
    # numbering — so a scroll-stopping line lands in the opening seconds.
    body = fulltext(row.url) or row.summary
    _hook, beats = scripter.script_deep(row.title, body, pb.deep_system)
    if not beats:
        beats = [(row.title, pb.intro_query)]
    beats = beats[: pb.deep_beats]            # keep it tight (~30s)
    scenes = [Scene(text=text, query=query or "technology abstract") for text, query in beats]
    scenes.append(Scene(text=pb.cta, query=pb.outro_query))
    return scenes

if __name__ == "__main__":
    sys.exit(main())
