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
from prism.repositories.registry import UserRegistry
from prism.services.embedder import Embedder
from prism.services.selector import Selector
from prism.services.reel_script import ReelScripter
from prism.services.reel_playbook import load_playbook
from reelforge import AzureSpeech, PexelsVisuals, Storyboard, Style, bundled_music, render

# The reel is a CONSUMER. For each reel lens (one profile per topic, provisioned in the registry)
# it features exactly what kb-sync published to that lens (its Edition) and renders vertical reels.
# It never selects audiences, never mints ids, never writes the registry — it only READS lenses.
# Per-topic creative (voice/playbook/music) = topics/<id>/pack.json settings.reel merged over
# config/reel.json defaults; the lens's interest (its source of truth) lives on the profile.

def _parse_args(argv=None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(description="Render vertical reels for each topic's reel lens.")
    ap.add_argument("--mode", choices=["roundup", "deep"], default="deep",
                    help="deep = one story per reel, explained; roundup = several stories in one reel")
    ap.add_argument("--topic", default="", help="render only this topic's reel lens (default: all)")
    ap.add_argument("--reels", type=int, default=0,
                    help="override reels-per-lens (0 = use the topic's creative config)")
    ap.add_argument("--count", type=int, default=5, help="stories to feature in roundup mode")
    ap.add_argument("--playbook", default="", help="force a creative playbook (default: per-topic config)")
    ap.add_argument("--from-digest", action="store_true", dest="from_digest",
                    help="feature the lens's published Edition (falls back to live selection if absent)")
    ap.add_argument("--upload", action="store_true", help="upload the mp4s to Blob digests/reels/<topic>/")
    ap.add_argument("--no-voice", action="store_true", help="skip the Azure Speech voiceover")
    ap.add_argument("--no-broll", action="store_true", help="skip Pexels b-roll (branded gradient)")
    ap.add_argument("--no-music", action="store_true", help="skip the background music bed")
    return ap.parse_args(argv)

def main(argv=None) -> int:
    args = _parse_args(argv)
    s = Settings()
    defaults = config_json("reel.json")           # global creative DEFAULTS

    blob = BlobStore(s.storage_account)
    if blob.enabled and not Path(KB_PATH).exists():
        blob.download_kb()
    kb = KnowledgeBase.open()
    gateway = ModelGateway(s.foundry_project_endpoint, s.foundry_model_name)
    scripter = ReelScripter(s.foundry_project_endpoint, gateway.model_for("brief"))
    embedder = Embedder(kb, s.foundry_project_endpoint, gateway.model_for("embed"))

    account = s.subscriber_storage or s.feedback_storage
    feeds = UserRegistry.from_subscribers(account).profiles_for_role("reel") if account else []
    if args.topic:
        feeds = [f for f in feeds if f.topic_id == args.topic]
    if not feeds:
        print("reel: no reel lenses provisioned (prism.cli.feeds add --kind reel ...) — nothing rendered")
        return 0

    date = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d")
    rendered: list[tuple[str, Path]] = []
    for feed in feeds:
        topic = feed.topic_id
        # Reel config is the reel layer's OWN (config/reel.json) — never the producer's topic pack.
        creative = defaults
        playbook = load_playbook(args.playbook or creative.get("playbook", "explainer"))

        # Resolve the lens's items: its published Edition (act on what kb-sync decided), else a live
        # selection steered by the lens's OWN interest + topic (the single source of truth).
        pool: list = []
        if args.from_digest and blob.enabled:
            edition = blob.read_edition(feed.filesafe_lens, date)
            pool = kb.items(edition.ids) if (edition and edition.ids) else []
            if pool:
                print(f"reel[{topic}]: featuring {len(pool)} item(s) from the lens Edition")
            else:
                print(f"reel[{topic}]: no Edition in Blob — using live selection")
        if not pool:
            interest_vec = embedder.embed_interest(feed.interest)
            weight = float(defaults.get("interest_weight", 20))
            want = max(args.reels or 2, args.count, 8)
            pool = Selector(kb).select(feed.lens, want, feed.min_score, interest_vec, weight, None, topic)
        if not pool:
            print(f"reel[{topic}]: nothing to feature — skipped")
            continue

        tts = None
        if not args.no_voice and s.speech_resource_id:
            tts = AzureSpeech(resource_id=s.speech_resource_id, region=s.speech_region,
                              voice=creative.get("voice", "en-US-AvaMultilingualNeural"),
                              style=creative.get("voice_style", ""), rate=creative.get("voice_rate", ""))
        music = "" if args.no_music else (creative.get("music") or bundled_music())
        style = Style(**{"caption_y": 0.62, "words_per_chunk": int(creative.get("words_per_chunk", 3)),
                         **playbook.style})

        # Build the scripts up front (one Foundry call each); deep = one reel per top story.
        jobs: list[tuple[str, list]] = []
        if args.mode == "deep":
            n = min(args.reels or int(creative.get("reels", 2)), len(pool))
            for k in range(n):
                body = fulltext(pool[k].url) or pool[k].summary
                suffix = f"-{k + 1}" if n > 1 else ""
                jobs.append((f"{date}-deep{suffix}.mp4", playbook.deep_scenes(pool[k].title, body, scripter)))
        else:
            jobs.append((f"{date}-roundup.mp4", playbook.roundup_scenes(pool[: args.count], scripter)))

        for name, scenes in jobs:
            # Fresh b-roll provider per reel: render() closes the provider when it finishes.
            visuals = PexelsVisuals(api_key=s.pexels_api_key) if (not args.no_broll and s.pexels_api_key) else None
            out = SCRATCH_DIR / "reels" / topic / name
            render(Storyboard(style=style, scenes=scenes, music=music), out, tts=tts, visuals=visuals)
            print(f"reel[{topic}]: wrote {out} ({out.stat().st_size} bytes, {len(scenes)} scenes, "
                  f"voice={'on' if tts else 'off'}, broll={'on' if visuals else 'off'}, "
                  f"music={'on' if music else 'off'})")
            if args.upload:
                blob.put_file(f"digests/reels/{topic}/{name}", out, "video/mp4")
            rendered.append((f"{topic}/{name}", out))

    print("\nDOWNLOAD:")
    for name, out in rendered:
        print(f"  local: {out.resolve()}")
        if args.upload and blob.enabled:
            print(f"  blob:  {s.storage_account}/{s.blob_container}/digests/reels/{name}")
    return 0

if __name__ == "__main__":
    sys.exit(main())

