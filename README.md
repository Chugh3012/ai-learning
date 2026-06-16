# ai-scout

A passwordless, cost-efficient pipeline that scans AI/LLM sources, ranks them with a Foundry
model, personalizes per user, and delivers a daily top-N — with a feedback loop that tunes it.
**Why it's built this way: [PLAN.md](PLAN.md).** What changed when: `git log`.

## Map
```
config/      what grows (sources.opml · users.json · tags.json · content.yml · *.json knobs)
tools/       the pipeline — kb_sync.py (orchestrator) calls rank · embed · curate · notify · feedback_ingest · draft
function/    passwordless Azure Function that captures feedback clicks
infra/       main.bicep — every Azure resource (source of truth)
tests/       offline unit tests for the deterministic core (run: python -m unittest discover -s tests)
.github/     pr-gate (compile + tests + ranking eval) · kb-sync cron · builder-radar (self-improve)
data/ digests/ drafts/   generated output (git-ignored)
```

## Run it
```sh
cp .env.example .env                          # fill in Azure resource names (no secrets)
python tools/kb_sync.py --help                # all flags and what they do
python tools/kb_sync.py --days 7 --no-upload  # local sync, no cloud writes
python tools/kb_sync.py --rank --deliver      # score + deliver each user's top-N
```
Auth is passwordless (Entra): `az login` locally, GitHub OIDC in CI. No keys or secrets.

Optional local reader backbone (RSSHub + FreshRSS) for browsing feeds: `docker compose up -d`.

## Extend it
Growth is config, not code — see the table in [PLAN.md](PLAN.md#where-things-grow-the-only-places).
Add a source, user, tag, or content profile by editing one config file. Adding an Azure resource
means editing `infra/main.bicep`, never the Portal.
