# ai-scout

Own, durable infrastructure that continuously scans for **new ways to use AI/LLMs**, helps
me learn, and later feeds an Instagram content funnel. Built slow, long-term, sleek.

**Read [PLAN.md](PLAN.md) first — it is the single source of truth.** This README is only the
quickstart for what exists today (Phase 1).

## What's here now (Phase 1 — Foundation)
Reused, battle-tested OSS as the backbone; we own only config.

- **RSSHub** (Layer A) — adapts sources without native feeds into RSS (kept for X/Twitter and
  token-based routes later).
- **FreshRSS** (Layer B) — aggregates, dedupes, stores; WebSub gives real push pubsub.
- `config/sources.opml` — curated AI/LLM sources to import (native-first; see `sources.yml`).
- `config/sources.yml` — readable source registry + topics + deferred notes.
- `config/tags.json` — keyword→topic rules used by the digest (Layer C).
- `config/proposals.yml` — discovery inbox for future self-growth (empty by design now).
- `tools/digest.py` — generates a grouped markdown digest from FreshRSS (stdlib only).

## Quickstart
Prereq: Docker Desktop.

```sh
cp .env.example .env          # then edit: set a strong FRESHRSS_ADMIN_PASSWORD, TZ
docker compose up -d          # starts rsshub (:1200) and freshrss (:8080)
```

1. Open FreshRSS at http://localhost:8080 and log in with the admin user/password from `.env`.
2. Subscriptions → Import → upload `config/sources.opml`.
3. Feeds refresh on a cron (`FRESHRSS_CRON_MIN`, default every 20 min). Done — curated AI
   feeds flow in, deduped and stored locally.

RSSHub-based feeds need the `rsshub` container running; they point at `http://localhost:1200`.
Native feeds work regardless. Reddit and GitHub-trending are deferred (see `config/sources.yml`).

## Digest (Layer C)
Generate a grouped markdown digest of recent items (reads FreshRSS via its API; tags from
`config/tags.json`):

```sh
python tools/digest.py --days 7        # writes digests/YYYY-MM-DD.md
```

Grow the tagging = add a topic/keyword in `config/tags.json`. No code change. Email delivery
is a config-gated extension for later (SMTP), not built until needed.

## Grow it (the only way sources grow)
Add a source = **one** `<outline>` in `config/sources.opml` **and** one entry in
`config/sources.yml`. Keep both deduped. No code changes. See PLAN.md.

## Data & privacy
- `.env` and `data/` are git-ignored. FreshRSS data persists in `data/freshrss/`.
- `digests/` holds generated digests; `data/kb/` is reserved for the owned KB (P3).

## What's next
P3 owned knowledge base (Azure) → P4 learning loop (LLM ranking) → P5 Instagram funnel.
Tracked in [PLAN.md](PLAN.md).
