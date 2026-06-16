# AI-Scout — North Star

> Why this project exists and the rules it must obey. This file holds only what is **durable**.
> For *what changed when*, read `git log` — never a changelog here.

## Mission
Own durable, cheap infrastructure that continuously scans for **new ways to use AI/LLMs**,
learns from feedback, and surfaces a personalized daily top-N per user. The agent maintaining
this repo is itself user 2 — it reads its own digest and improves the app.

## Principles (non-negotiable — a change that breaks one is wrong)
1. **Reuse, don't reinvent.** Build on battle-tested OSS and platform services. Custom code only
   at the seams we own.
2. **Own the data.** Curated knowledge lives in our own SQLite KB, independent of any tool.
3. **Growth = config, not code.** A new source/user/tag/profile is one config line, never a module.
4. **Revise, don't append.** One source of truth per concern. Prune; no bloat. No doc that merely
   restates code, `--help`, or `git log` — that only rots.
5. **Decoupled + graceful.** Each stage (rank, embed, draft, deliver, feedback) is optional and
   no-ops when its backing service is unconfigured; one stage never breaks the pipeline.
6. **Human-gated automation.** The self-improve loop opens draft PRs; a human reviews and merges.
   No auto-merge to `main`.
7. **Entra-first, passwordless.** `DefaultAzureCredential` everywhere — `az login` locally, GitHub
   OIDC in CI. No keys, connection strings, or stored secrets, in code or config.

## Architecture
Generic, swappable stages over one owned store. Flow:

`sources → ingest → KB → rank + embed → curate → deliver (per user) → feedback → KB`

- **Ingest** — `tools/kb_sync.py` reads `config/sources.opml` (feedparser), dedupes into the owned
  SQLite KB, backs it up to Azure Blob (OIDC). Optional local reader backbone: RSSHub + FreshRSS
  (`docker-compose.yml`).
- **Owned KB** — SQLite, schema `source · item · tag · signal · draft · embedding`. The generic
  `signal(item_id, kind, value, ts)` table holds everything; `kind` is a namespaced string
  (`relevance`, `affinity:<user>`, `sent:<user>`, `fb_*:<user>`) so new signal types need **no
  migration**.
- **Rank + embed** — a Foundry model scores each item 0–100 for AI-usefulness (shared quality
  gate); `text-embedding-3-large` embeds each item once. Both passwordless, incremental, capped.
- **Personalize (two-tower)** — each user is one config entry with an optional `interest`
  sentence; per-user score = shared relevance + interest match (cosine, a dot product) + that
  user's feedback affinity. Cost is `O(items + users)`, not `items × users`.
- **Deliver** — per user, top-N above their `min_score`, via their channel: `email` (Azure
  Communication Services) or `digest` (a markdown file). Feedback links work on every channel.
- **Feedback** — a passwordless Function records clicks to Azure Tables; a daily step drains them
  into per-user affinity and ages out implicit negatives (shown-but-not-acted).
- **Self-improve** — GitHub Agentic Workflows builds the builder's digest, a coding agent opens a
  draft PR, `pr-gate` (compile + unit tests + ranking eval) guards it, a human merges.

## Where things grow (the only places)
| To add… | Edit | Not |
|---|---|---|
| a source | `config/sources.opml` (+ `sources.yml`) | code |
| a user | `config/users.json` (id, channel, top, min_score, interest) | code |
| a tag/topic | `config/tags.json` | code |
| a content profile | `config/content.yml` | code |
| an Azure resource | `infra/main.bicep` | the Portal/CLI |

## Locked decisions
- **SQLite is the owned system of record.** Azure Blob = offsite backup (Entra RBAC, no keys).
  Postgres/vector-DB only if scale ever demands it — the sync layer is decoupled, so it's a swap.
- **Infra-as-Code:** `infra/*.bicep` is the source of truth; `az deployment group what-if` verifies.
- **Quality is gated, not asserted.** `pr-gate` runs compile + offline unit tests (`tests/`) + a
  labeled ranking eval (`tools/eval_rank.py`) on every PR. Correctness lives in gates, not prose.
- **Don't fine-tune yet.** `tools/feedback_export.py` is the seam; wait for ≥200 feedback examples.
- **Cost discipline:** pay-per-use, near-zero idle, tear-down friendly.

## Open questions (resolve when reached)
- Always-on host for FreshRSS WebSub push if/when real-time ingest matters (Actions is cron-only).
- Publishing path for content drafts (Instagram/LinkedIn) — manual export vs Graph API; only with a
  real account (non-Entra auth, hard to reverse).
