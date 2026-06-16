# ai-scout — repository brief for AI coding agents

You are working on **ai-scout**: an owned, passwordless, cost-efficient pipeline that scans
AI/LLM sources → ranks them with a Foundry model → personalizes per user → delivers a daily
top-N (email or digest) with a feedback loop. You may be the **GitHub Copilot coding agent**
invoked from a "🤖 Builder radar" issue — in that case you are *user 2* of this app (the
maintainer), acting on items the pipeline surfaced as relevant to building/operating it.

## Non-negotiable principles (a PR that breaks these will be rejected)
- **Passwordless / Entra-first.** All Azure access uses `DefaultAzureCredential` (OIDC in CI,
  `az login` locally). NO keys, connection strings, account secrets, or SAS in code or config.
- **Infra-as-Code first.** `infra/main.bicep` is the source of truth for every Azure resource.
  If a change needs infra, edit the Bicep — never hand-provision as the source of truth.
- **The eval-gate must stay green.** `tools/eval_rank.py` grades ranking quality on a labeled
  golden set; `.github/workflows/pr-gate.yml` runs it (plus a compile check) on EVERY PR and is
  the **merge authority** — a PR auto-merges only when this gate is green. Don't regress it.
- **Config over code.** Growth = add a row to a JSON/OPML/YAML config, not a new code path.
  Sources → `config/sources.opml`. Users → `config/users.json`. Tags → `config/tags.json`.
- **Sleek, no bloat.** Revise files in place; don't append duplicate logic or scaffold unused
  abstractions. Don't add markdown docs unless asked. One focused PR per coherent change.
- **Every stage is optional + graceful.** Ranking/draft/email/feedback each no-op (never crash
  the pipeline) when their backing service is unconfigured.

## Architecture (what already exists — do NOT reinvent)
- **Ingest + KB:** `tools/kb_sync.py` reads `config/sources.opml` (feedparser), dedupes into an
  owned SQLite KB `data/kb/kb.sqlite` (schema: `source · item · tag · signal`), backed up to
  Azure Blob via OIDC. The generic `signal(item_id, kind, value, ts)` table holds everything —
  new signal types need NO migration (kinds are namespaced strings, e.g. `relevance`,
  `affinity:<user>`, `sent:<user>`, `fb_vote:<user>`).
- **Ranking:** `tools/rank.py` scores items 0–100 via a Foundry model (`gpt-4.1-mini`,
  deployment `mini`) through `tools/foundry.py` (`openai_client`, passwordless). Calibrated
  rubric + AI-topicality gate. Chosen by a labeled eval (`.foundry/`), not vibes.
- **Curation:** `tools/curate.py` — `dedup` (Jaccard on titles) + `diversify` (per-source/topic
  caps). `config/curate.json` tunes it.
- **Delivery (multi-user):** `tools/notify.py` `deliver_all` — one SHARED ranking; each user in
  `config/users.json` gets their top-N reordered by their own `affinity:<user>`, above their
  `min_score` bar (quiet day → nothing). Channels: `email` (Azure Communication Services) and
  `digest` (a markdown file). Feedback links (👍/👎/save) work on every channel.
- **Feedback:** `function/function_app.py` (Azure Functions, passwordless MI → Tables) records a
  click as an event; `tools/feedback_ingest.py` drains events → per-user `affinity`. Tokens are
  per-(user,item,action).
- **Fine-tune seam:** `tools/feedback_export.py` exports KB feedback to DPO/SFT JSONL on demand
  (don't fine-tune until ≥200 examples — `MIN_PAIRS`).
- **CI:** `eval-gate.yml` (quality gate), `kb-sync.yml` (daily cron: ingest→rank→deliver→ this
  self-improve issue).

## Stack
Python 3.13; `azure-ai-projects`, `azure-identity`, `azure-storage-blob`,
`azure-communication-email`, `azure-data-tables`, `feedparser`, `trafilatura`. Azure: Foundry
project `scout`, Blob, ACS Email, Functions (Flex), all in `rg-ai-scout`, passwordless.

## How to work a "Builder radar" issue
1. Each listed item is a candidate improvement (an SDK change to adapt to, a dep upgrade, an
   agent/eval/RAG technique). For genuinely useful ones, make the change in a focused PR.
2. **Not every item warrants action — "no change" is a valid outcome.** Don't force PRs.
3. Respect every principle above. If infra changes, update `infra/main.bicep`. Run/keep the
   eval-gate green. Prefer config edits over new code.
4. Open a PR for human review. **Do NOT merge to `main`.** Whether your PR is merged or closed
   is itself the feedback signal — make each PR genuinely worth merging.

## Commands
- Local sync (no cloud writes): `python tools/kb_sync.py --days 7 --no-upload`
- Ranking eval gate: `python tools/eval_rank.py` (exit 0 = pass)
- Compile check: `python -m py_compile tools/*.py function/function_app.py`
