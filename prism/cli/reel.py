from __future__ import annotations

import argparse
import datetime as dt
import sys
from pathlib import Path

from prism.lib.settings import Settings
from prism.lib.config import SCRATCH_DIR, KB_PATH, config_json
from prism.lib.gateway import ModelGateway
from prism.lib.text import fulltext, digest_item_ids
from prism.repositories.blob import BlobStore
from prism.repositories.knowledge import KnowledgeBase
from prism.repositories.models import Item
from prism.repositories.registry import UserRegistry
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
    ap.add_argument("--reels", type=int, default=1,
                    help="how many reels to render this run (deep mode = one per top story)")
    ap.add_argument("--from-digest", action="store_true", dest="from_digest",
                    help="feature exactly what kb-sync published to the reel lens digest in Blob "
                         "(falls back to live selection if no digest is found)")
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

    # Consume exactly what kb-sync published to the reel lens (decoupled consumer), or — if no
    # digest is in Blob yet — steer a fresh selection by the configured interest sentence.
    pool = _pool_from_digest(blob, kb, s) if args.from_digest else []
    if pool:
        print(f"reel: featuring {len(pool)} item(s) from the reel-lens digest")
    else:
        interest_vec = Embedder(kb, s.foundry_project_endpoint,
                                gateway.model_for("embed")).embed_interest(cfg.get("interest", ""))
        weight = float(cfg.get("interest_weight", 20))
        want = max(args.count, args.reels, 8)
        pool = Selector(kb).select(_LENS, want, 0.0, interest_vec, weight, None, args.topic)
    if not pool:
        print("reel: no items to feature — nothing rendered")
        return 0

    tts = None
    if not args.no_voice and s.speech_resource_id:
        tts = AzureSpeech(resource_id=s.speech_resource_id, region=s.speech_region,
                          voice=cfg.get("voice", "en-US-AvaMultilingualNeural"),
                          style=cfg.get("voice_style", ""), rate=cfg.get("voice_rate", ""))
    music = "" if args.no_music else (cfg.get("music") or bundled_music())
    base_style = {"caption_y": 0.62, "words_per_chunk": int(cfg.get("words_per_chunk", 3))}
    style = Style(**{**base_style, **playbook.style})

    # Build the reels' scripts up front (one Foundry call each); deep mode = one reel per top story.
    date = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d")
    jobs: list[tuple[str, list]] = []
    if args.mode == "deep":
        n = min(max(args.reels, 1), len(pool))
        for k in range(n):
            suffix = f"-{k + 1}" if n > 1 else ""
            jobs.append((f"{date}-deep{suffix}.mp4", _deep_scenes(pool[k], scripter, playbook)))
    else:
        jobs.append((f"{date}-roundup.mp4", _roundup_scenes(pool[: args.count], scripter, playbook)))

    rendered: list[tuple[str, Path]] = []
    for name, scenes in jobs:
        # Fresh b-roll provider per reel: render() closes the visuals provider when it finishes.
        visuals = PexelsVisuals(api_key=s.pexels_api_key) if (not args.no_broll and s.pexels_api_key) else None
        out = SCRATCH_DIR / "reels" / name
        render(Storyboard(style=style, scenes=scenes, music=music), out, tts=tts, visuals=visuals)
        print(f"reel: wrote {out} ({out.stat().st_size} bytes, {len(scenes)} scenes, "
              f"voice={'on' if tts else 'off'}, broll={'on' if visuals else 'off'}, "
              f"music={'on' if music else 'off'})")
        rendered.append((name, out))

    print("\nDOWNLOAD:")
    for name, out in rendered:
        uploaded = bool(args.upload and blob.put_file(f"digests/reels/{name}", out, "video/mp4"))
        print(f"  local: {out.resolve()}")
        if uploaded:
            print(f"  blob:  {s.storage_account}/{s.blob_container}/digests/reels/{name}")
            print(f"  az storage blob download --account-name {s.storage_account} --container-name "
                  f"{s.blob_container} --name digests/reels/{name} --file {name} --auth-mode login")
    return 0

def _pool_from_digest(blob: BlobStore, kb: KnowledgeBase, s: Settings) -> list:
    # Read the items kb-sync already selected for the reel lens (role 'reel') from its published
    # digest in Blob, in rank order. Decoupled: the producer (kb-sync) decides, this consumer acts.
    # Returns [] on any miss so the caller falls back to live selection (graceful).
    account = s.subscriber_storage or s.feedback_storage
    if not (blob.enabled and account):
        return []
    try:
        prof = UserRegistry.from_subscribers(account).profile_for_role("reel")
    except Exception as e:
        print(f"reel: could not resolve reel profile ({e})")
        return []
    if not prof:
        return []
    date = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d")
    data = blob.download_digest(f"{prof.filesafe_lens}-{date}.md")
    if not data:
        print("reel: no reel-lens digest in Blob for today — using live selection")
        return []
    ids = digest_item_ids(data.decode("utf-8", "replace"))
    with kb.session() as ses:
        return [it for iid in ids if (it := ses.get(Item, iid)) is not None]

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
