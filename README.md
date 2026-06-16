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
- `config/tags.json` — keyword→topic rules used for KB tagging (Layer C).
- `config/proposals.yml` — discovery inbox for future self-growth (empty by design now).
- `tools/kb_sync.py` — builds the owned SQLite KB from the feeds (the orchestrator).

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

## Owned knowledge base & delivery (Layers C/D/F)
The **owned system of record is a SQLite KB** built directly from the feeds, backed up to
Azure Blob. It runs in the cloud on a schedule (GitHub Actions) so it works whether or not
this laptop is on. FreshRSS stays as an optional **local reader**.

```sh
python tools/kb_sync.py --days 7                # feeds → data/kb/kb.sqlite → Azure Blob
python tools/kb_sync.py --days 7 --rank         # also score relevance (Microsoft Foundry)
python tools/kb_sync.py --rank --draft          # also draft top items for review
python tools/kb_sync.py --rank --deliver        # also deliver each user's top-N (users.json)
python tools/kb_sync.py --no-upload             # local only, skip Blob
```

- Tagging grows via `config/tags.json` (keyword→topic). No code change.
- **Relevance ranking (P4):** a Foundry model (`gpt-4.1-mini`, deployment `mini`) scores
  each new item 0–100 for "new ways to USE AI"; scores live in the KB `signal` table and
  order delivery. Uses the Foundry SDK `AIProjectClient.get_openai_client()` —
  passwordless (Entra). Incremental + capped (`--rank-max`) so cost stays sub-cent/run.
- **Content drafts (P5):** `--draft` turns the top-scored items into human-review drafts
  (KB `draft` table → `drafts/YYYY-MM-DD-review.md`). The content target is a **profile in
  `config/content.yml`** (default `social`) — add LinkedIn/blog/etc. = add a profile, no
  code. Nothing is published; publishing to any platform is a manual, opt-in future step.
- **Delivery (P6/P11):** `--deliver` sends each user in `config/users.json` their top-N
  not-yet-seen ranked items (a short crux + title + source link) via their channel —
  `email` (**Azure Communication Services**, passwordless) or `digest` (a dated markdown
  file under `digests/`). Each item is sent once per user (KB `signal` kind=`sent:<user>`).
  Feedback links (👍/👎/save) work on every channel via the capture Function.
- Auth is **passwordless** (Entra): `az login` locally, GitHub OIDC in CI. No keys/secrets.
- Cloud cron: `.github/workflows/kb-sync.yml` (daily, `--rank --feedback --deliver`). Azure:
  resource group `rg-ai-scout`, Storage (shared-key disabled), container `knowledge`, Foundry
  resource `aiscoutageony` + project `scout` + `mini` deployment, user-assigned managed
  identity `id-ai-scout-gh` federated to this repo's `main`.

## Grow it (the only way sources grow)
Add a source = **one** `<outline>` in `config/sources.opml` **and** one entry in
`config/sources.yml`. Keep both deduped. No code changes. See PLAN.md.

## Data & privacy
- `.env`, `.venv/`, and `data/` are git-ignored. Owned KB persists in Azure Blob + `data/kb/`.
- `digests/` holds per-user `digest`-channel deliveries (the agent's channel). Owned KB
  persists in Azure Blob + `data/kb/`.

## What's next
Content-output targets grow by adding profiles in `config/content.yml`. Actual publishing
(Instagram/LinkedIn/etc.) is a manual, opt-in step — added only when an account + auth
exist. Tracked in [PLAN.md](PLAN.md).
