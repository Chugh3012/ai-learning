"""`python -m ai_scout.cli.sync` — the daily pipeline run (composition root / DI container).

Wires repositories (KnowledgeBase, BlobStore, FeedbackStore, UserRegistry) + services (Ingestor,
Ranker, Embedder, FeedbackService, Orchestrator, SourceDiscoverer, ContentProducer) and runs the
requested stages. Each stage is optional and graceful. Passwordless throughout.

  --rank      score new items + embed them      --feedback  ingest gesture events -> affinity
  --deliver   scheduled delivery (cadence)       --produce   on-demand <user>:<profile> lenses
  --discover  propose new feeds                  --no-upload local only (skip Blob)
"""
from __future__ import annotations

import argparse
import sys

from ai_scout.lib.config import load_env
from ai_scout.repositories.blob import BlobStore
from ai_scout.repositories.feedback import FeedbackStore
from ai_scout.repositories.knowledge import KnowledgeBase
from ai_scout.repositories.registry import UserRegistry
from ai_scout.services.brief_builder import BriefBuilder
from ai_scout.services.discoverer import SourceDiscoverer
from ai_scout.services.embedder import Embedder
from ai_scout.services.feedback_service import FeedbackService
from ai_scout.services.ingest import Ingestor
from ai_scout.services.producer import ContentProducer, write_review
from ai_scout.services.ranker import Ranker
from ai_scout.services.selector import Selector
from ai_scout.services.delivery.orchestrator import Orchestrator


def _parse_args(argv=None) -> argparse.Namespace:
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=7)
    ap.add_argument("--no-upload", action="store_true", help="skip Blob download/upload (local only)")
    ap.add_argument("--rank", action="store_true", help="score new items for relevance + embed them")
    ap.add_argument("--rank-max", type=int, default=400, help="max items to score per run (cost cap)")
    ap.add_argument("--embed-max", type=int, default=2000, help="max items to embed per run")
    ap.add_argument("--deliver", "--email", action="store_true", dest="deliver",
                    help="scheduled pass: deliver every due profile via its channel")
    ap.add_argument("--produce", default="",
                    help="on-demand: comma-separated <user_id>:<profile_id> lenses (bypasses cadence)")
    ap.add_argument("--feedback", action="store_true",
                    help="ingest per-lens feedback events and recompute affinity")
    ap.add_argument("--discover", action="store_true",
                    help="propose new feeds into config/proposals.yml from recurring item links")
    return ap.parse_args(argv)


def main(argv=None) -> int:
    # Force UTF-8 so a Windows cp1252 console can't crash on a non-ASCII print.
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:  # noqa: BLE001
            pass

    args = _parse_args(argv)
    env = load_env()
    endpoint = env.get("FOUNDRY_PROJECT_ENDPOINT", "")
    model = env.get("FOUNDRY_MODEL_NAME", "nano")
    embed_model = env.get("FOUNDRY_EMBED_NAME", "embed")

    blob = BlobStore(env.get("STORAGE_ACCOUNT", ""), env.get("BLOB_CONTAINER", "knowledge"))
    use_blob = not args.no_upload and blob.enabled
    if use_blob:
        blob.download_kb()

    kb = KnowledgeBase.open()
    new_items, total = Ingestor(kb).sync()

    if args.rank:
        Ranker(kb, endpoint, model).score_unscored(args.days, args.rank_max)
        Embedder(kb, endpoint, embed_model).embed_unembedded(args.embed_max)

    registry = UserRegistry.load()
    feedback_store = FeedbackStore(env.get("FEEDBACK_STORAGE", ""))

    if args.feedback:
        FeedbackService(kb, feedback_store).ingest(registry.feedback_lenses())

    if args.deliver or args.produce:
        orchestrator = Orchestrator(
            kb, registry, Embedder(kb, endpoint, embed_model), Selector(kb),
            BriefBuilder(kb, endpoint, model), ContentProducer(kb, endpoint, model),
            feedback_store, env)
        if args.deliver:
            orchestrator.run()
        if args.produce:
            orchestrator.run(targets={t.strip() for t in args.produce.split(",") if t.strip()})

    if args.discover:
        SourceDiscoverer(kb).discover()

    review = write_review(kb)
    kb.close()
    print(f"sync: +{new_items} new, {total} total items")

    if use_blob:
        blob.upload_kb(review)
    elif not args.no_upload:
        print("note: STORAGE_ACCOUNT not set — skipped Blob (set it in .env or repo Variables)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
