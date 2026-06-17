from __future__ import annotations

import argparse
import sys

from ai_scout.lib.settings import Settings
from ai_scout.lib.metrics import Metrics
from ai_scout.lib import foundry
from ai_scout.repositories.blob import BlobStore
from ai_scout.repositories.feedback import FeedbackStore
from ai_scout.repositories.knowledge import KnowledgeBase
from ai_scout.repositories.registry import UserRegistry
from ai_scout.services.brief_builder import BriefBuilder
from ai_scout.services.discoverer import SourceDiscoverer
from ai_scout.services.embedder import Embedder
from ai_scout.services.feedback_service import FeedbackService
from ai_scout.services.ingest import Ingestor
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
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

    args = _parse_args(argv)
    s = Settings()
    endpoint = s.foundry_project_endpoint
    model = s.foundry_model_name
    embed_model = s.foundry_embed_name

    blob = BlobStore(s.storage_account, s.blob_container)
    use_blob = not args.no_upload and blob.enabled
    if use_blob:
        blob.download_kb()

    metrics = Metrics(s.metrics_dce, s.metrics_dcr_rule_id, s.metrics_stream)
    kb = KnowledgeBase.open()
    ingestor = Ingestor(kb)
    new_items, total = ingestor.sync()
    metrics.add("ingested", new_items)
    metrics.add("feeds_failed", ingestor.feeds_failed)

    if args.rank:
        metrics.add("ranked", Ranker(kb, endpoint, model).score_unscored(args.days, args.rank_max))
        metrics.add("embedded", Embedder(kb, endpoint, embed_model).embed_unembedded(args.embed_max))

    registry = UserRegistry.load()
    feedback_store = FeedbackStore(s.feedback_storage)

    if args.feedback:
        metrics.add("voted", FeedbackService(kb, feedback_store).ingest(registry.feedback_lenses()))

    if args.deliver or args.produce:
        orchestrator = Orchestrator(
            kb, registry, Embedder(kb, endpoint, embed_model), Selector(kb),
            BriefBuilder(kb, endpoint, model),
            feedback_store, blob if use_blob else None, s, metrics)
        if args.deliver:
            orchestrator.run()
        if args.produce:
            orchestrator.run(targets={t.strip() for t in args.produce.split(",") if t.strip()})

    if args.discover:
        SourceDiscoverer(kb).discover()

    for k, v in kb.metrics_snapshot().items():
        metrics.add(k, v)
    for lens in registry.feedback_lenses():
        eng = kb.engagement(lens)
        for k, v in eng.items():
            metrics.add(f"engaged_{k}", v, lens=lens)
        reached = eng["votes"] + eng["saves"] + eng["clicks"]
        if eng["sent"]:
            metrics.add("keep_rate", reached / eng["sent"], lens=lens)

    kb.close()
    print(f"sync: +{new_items} new, {total} total items")

    u = foundry.usage_snapshot()
    metrics.add("tokens_total", u["total"])
    metrics.add("tokens_prompt", u["prompt"])
    metrics.add("tokens_completion", u["completion"])
    metrics.add("cost_usd", foundry.cost_usd())
    metrics.flush()

    if use_blob:
        blob.upload_kb()
    elif not args.no_upload:
        print("note: STORAGE_ACCOUNT not set — skipped Blob (set it in .env or repo Variables)")
    return 0

if __name__ == "__main__":
    sys.exit(main())
