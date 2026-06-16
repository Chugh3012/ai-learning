# AI-Scout — Plan & North Star

> Single source of truth for this project. Revise this file; never append duplicate sections.
> If work drifts, re-read this first.

## Mission
Own durable infrastructure that continuously scans for **new ways to use AI/LLMs**, helps me
learn from it, and later feeds an **Instagram content funnel**. Build slow, long-term, sleek.

## Principles (non-negotiable)
1. **Reuse, don't reinvent.** Build on battle-tested OSS (RSSHub, FreshRSS). Custom code only
   at seams we own.
2. **Own the data.** Curated knowledge lives in our own DB, independent of any tool.
3. **Growth = data, not code.** New source/topic = one config line, never a new module.
4. **Revise, don't append.** One source of truth per concern. Prune; no bloat.
5. **Decoupled stages.** Each layer can evolve or be swapped without breaking others.
6. **Human-gated automation.** Self-discovery proposes; human approves; system stays curated.
7. **Entra-first, passwordless.** Use Microsoft Entra ID everywhere possible — managed
   identity for Azure-to-Azure auth, Entra auth for Postgres, RBAC for Blob, and GitHub
   Actions via OIDC federated credentials. No app keys / connection strings / stored secrets.

## Architecture (5 layers)
| Layer | Role | Tool / Owned |
|-------|------|--------------|
| A. Ingest | source → RSS adapters (X, Reddit, GitHub, YouTube, arXiv, HN, Product Hunt, blogs) | RSSHub (docker) |
| B. System of record | WebSub push (pubsub) · dedupe · store | FreshRSS (docker) |
| C. Curation | tags · saved queries · later LLM relevance scoring | FreshRSS + config |
| D. Owned knowledge base | durable archive + feedback signals (the long-term asset) | our Postgres/SQLite + object store |
| E. Content funnel (future) | KB item → LLM draft (caption/carousel) → review → schedule | decoupled service |

Flow: A → B → C → D → E. Two feedback loops into D/C: **discovery** (grows sources) and
**feedback** (grows ranking). Both human-gated.

## Config-as-code (the only places things grow)
- `sources.opml` + `sources.yml` — the curated source list.
- `proposals.yml` — system-suggested sources/topics awaiting human approval (then merged, deduped).
- `docker-compose.yml` — infra. `.env` — secrets. Owned DB — knowledge. All in git.
- Registry pattern reserved for any future connector/sink: drop one self-registering file, edit no core.

## Phased roadmap
- **P1 Foundation** — repo skeleton + `docker-compose.yml` (RSSHub+FreshRSS) + curated
  `sources.opml` + `.env.example` + README. Done when: feeds flow, dedupe works, stored locally.
- **P2 Curation** — tag rules + saved queries → stable curated feed + markdown/email digest.
- **P3 Owned KB** — sync FreshRSS API → local SQLite KB (generic schema item·source·tag·signal)
  + push a copy to Azure Blob (Entra RBAC). Done when: data is ours, durably backed up, cheap.
- **P4 Learning loop** — weekly digest + optional LLM ranking/summary of novel AI usage.
- **P5 Content drafts** — config-driven profiles (`config/content.yml`) turn top-ranked KB
  items into human-review drafts. Output target = config, not code. Publishing = manual/opt-in.

Each phase is independently valuable and verifiable. Don't build ahead of what's proven.

## Self-growth ("Jarvis") seams reserved in P1
- Generic KB schema: `item · source · tag · signal` (new signal types need no schema change).
- `proposals.yml` convention for the discovery loop.
- Registry pattern for connectors/sinks.

## Decisions locked
- Storage: SQLite is the owned KB system of record (P3). **Azure Blob = durable offsite
  backup**, Entra RBAC only (no keys). Postgres DEFERRED to P4/P5 — adopt only when concurrent
  access or vector search actually needs it (sync layer is decoupled, so it's a swap not a rewrite).
- Scheduling: container-native / cron; no bespoke scheduler.
- **Infra-as-Code**: `infra/*.bicep` is the source of truth for all Azure resources. Change
  infra there, not in the Portal/CLI. `az deployment group what-if` verifies fidelity.
- X/Twitter: via RSSHub, no paid API.
- No LLM summarization in P1–P2; reserved for P4.
- Cost discipline: no always-on cloud compute until a phase truly needs it. Prefer
  pay-per-use / near-zero-idle services. Tear-down friendly (nothing to "nuke").

## Hosting & cloud (adopt per phase, never before a phase needs it)
- **GitHub** (from P1): repo = source of truth; **Actions cron** runs digest + discovery
  jobs (no server); GHCR for custom images; Dependabot keeps deps fresh.
- **Local Docker** (P1–P2): prove RSSHub + FreshRSS on my machine first.
- **Azure** (from P3, when always-on/ownership matters): Container Apps or VM + Azure Files
  for RSSHub/FreshRSS; **owned KB = SQLite backed up to Azure Blob** (Entra RBAC, no keys).
  Postgres only if/when P4–P5 need it.
- **Azure OpenAI / Microsoft Foundry** (P4–P5): ranking, summaries, content drafts.
- Note: FreshRSS WebSub push needs an always-on host (Actions is cron-only) → that piece
  is local in P1–P2, Azure from P3.

## Open questions (resolve when reached)
- Always-on host at P3: Azure Container Apps vs small VM/VPS vs home server.
- LLM provider for P4: Azure OpenAI / Foundry vs OpenAI vs local.
- Instagram publishing method for P5 (manual export vs Graph API).

## Status
- [x] P1  - [x] P2  - [x] P3  - [x] P4  - [x] P5  - [x] P6 (consumption)  - [x] P7 (feedback)  - [x] P8 (quality)  - [x] P9 (model)  - [x] P10 (sources+CI)  - [x] P11 (multi-user)
- P1–P4 DONE (2026-06-15): ingest (RSSHub+FreshRSS) → tag+digest → owned SQLite KB → Azure
  Blob (passwordless OIDC) → Foundry-project relevance ranking. All verified in cloud.
- P5 DONE (2026-06-15): content drafts. tools/draft.py + config/content.yml profiles
  (default 'social', platform-agnostic) generate human-review drafts into KB `draft` table
  → drafts/YYYY-MM-DD-review.md. Foundry SDK, passwordless, incremental, cost-capped
  (--draft-min/--draft-max). Output target = config, not code (add a profile to extend).
  Verified locally (3 drafts). PUBLISHING is intentionally NOT built (manual/opt-in).
- Publishing (future, opt-in): Instagram needs Meta pro account + Page + PPA + app review +
  OAuth + public JPEG hosting (non-Entra, hard to reverse). Add only with a real account.
- P6 DONE (2026-06-15): daily email of top-5 ranked items (one-line "why it matters" +
  source link) via Azure Communication Services Email, passwordless (managed identity).
  tools/notify.py + shared tools/foundry.py helper. Each item emailed once (KB signal
  kind='emailed'). Azure: email-ai-scout (Email svc) + AzureManaged domain + acs-ai-scout
  (Communication), role "Communication and Email Service Owner" on me+UAMI. GH vars
  ACS_ENDPOINT/EMAIL_SENDER/EMAIL_TO; workflow runs --rank --email. Verified: real email sent.
  Feedback (next, opt-in): 👍/👎, save, click → KB signal table; leaning tiny passwordless
  Azure Function (consumption ~$0). Email will carry feedback links when endpoint exists.
  Delivery channel-agnostic (WhatsApp deferred = Meta Business + templates + tokens, non-Entra).
- P7 DONE (2026-06-16): feedback loop, NewsBlur-style (researched first — no drop-in OSS fits
  passwordless-Azure + owned-SQLite). Email carries 👍/👎/⭐save links + click-tracked source,
  each an opaque per-(item,action) token in Azure Table `feedbacktokens`. A passwordless Flex-
  Consumption Function (function/function_app.py, system MI → Tables) validates the token and
  records an event in `feedbackevents` — never touches the SQLite KB (decoupled, no write races).
  Daily `kb_sync --feedback` (tools/feedback_ingest.py) drains events → KB fb_* signals →
  recomputes a bounded per-source/per-topic `affinity` (additive, config/feedback.json), blended
  into email + digest ordering. Idempotent (votes changeable). Verified end-to-end in cloud:
  real clicks → 200 → +20/−20 affinity → reorder. GH vars FEEDBACK_URL/FEEDBACK_STORAGE.
- P8 DONE (2026-06-16): ranking + digest QUALITY. (1) rank.py rubric rewritten — calibrated
  bands + AI-topicality gate + applied-over-academic bias, scored on title+summary not title
  only → scores now spread 0-100 (was all ~90). (2) tools/curate.py: dedup() collapses near-
  duplicate headlines (Jaccard over title tokens) + diversify() caps per-source/per-topic (MMR-
  style); config/curate.json knobs. Applied to email top-N (pool×6 then curate) and digest. (3)
  notify.py: best-effort trafilatura full-text fetch deepens the email crux (falls back to feed
  summary). (4) foundry.log_usage() prints per-call tokens for cost visibility. Verified: score
  distribution healthy, diversity cap works. KNOWN RESIDUAL: nano over-scores some title-only HN
  front-page items (Typst, a game) despite the gate — that source (HN frontpage) is general-tech
  noise; tightening/replacing it is the real lever (follow-up).
- P9 DONE (2026-06-16): model selection by labeled eval + source fix. (a) Replaced noisy HN
  frontpage feed with an AI-filtered HN query (points>=30) in sources.opml/yml. (b) Ran a
  Foundry-style graded comparison on a hand-labeled golden set (.foundry/datasets/golden_rank_v1
  .jsonl, 33 items, tiers + non-AI traps) with real ranking metrics (Spearman, nDCG@5, prec@5,
  non-AI leak) + token cost. Results (.foundry/results/model_compare_v1.json): nano spearman .51
  / leak 85 (scored a 'C++ ray tracer WITHOUT AI' an 85!); gpt-4.1-mini .78 / prec@5 1.0 / leak 5;
  gpt-5-mini .77 but 4× cost + 8× slower (reasoning). DECISION: switched ranking/drafting model to
  gpt-4.1-mini (deployment 'mini', cap50) — ~$0.39/mo vs nano's ~$0.10 (negligible). GH var + .env
  FOUNDRY_MODEL_NAME=mini; added to Bicep. nano kept deployed (cheap, fallback). Eval deployments
  torn down. Golden set retained for future regression.
- P10 DONE (2026-06-16): sources + CI gate + fine-tune seam. (a) Sources: verified candidate
  feeds live via feedparser, cut arXiv 3→1 (kept cs.CL; dropped cs.AI/cs.LG floods = ~500 fewer
  academic items/day to rank), added Latent Space + Interconnects (high-signal applied). (b) CI
  eval gate: tools/eval_rank.py grades the production prompt over the golden set vs config/eval.json
  thresholds (spearman>=.65, ndcg5>=.65, prec5>=.8, leak<=30); .github/workflows/eval-gate.yml runs
  it on PRs touching rank/prompt/eval (OIDC, passwordless). Local pass: spearman .70 / ndcg .80 /
  prec 1.0 / leak 5. (c) Fine-tune seam: tools/feedback_export.py harvests KB feedback into DPO
  (👍 chosen vs 👎 rejected) or SFT (item→endorsed score) JSONL on demand. DECISION (explicit): do
  NOT fine-tune yet — needs ~200+ examples (MIN_PAIRS) and the loop is new; cheap additive-affinity
  (P7) carries personalization until then. Exporter proven to run (0 rows now, correct guidance).
- P11 DONE (2026-06-16): MULTI-USER (the app's tenancy test). A user = config/users.json entry
  {id, channel, top}; everyone shares the ONE relevance ranking; personalization = each user's own
  +/- feedback only (NO per-user prompt — rejected that approach). Per-user state namespaced in
  signal.kind: sent:<id>, affinity:<id>, fb_vote/save/click:<id> (no schema change — generic kind).
  notify.deliver_all loops users → _select_for_user (shared rank + that user's affinity, minus their
  sent) → curate → channel: 'email' (ACS + feedback links) or 'digest' (digests/<id>-DATE.md, the
  agent's channel). feedback_ingest now per-user; Function tokens+events carry user (RowKey=<user>:<row>),
  redeployed. kb_sync._migrate_legacy_signals one-time renames old global emailed/affinity/fb_* →
  :primary (idempotent) so the original user isn't re-sent or de-personalized. --email kept as alias
  for --deliver. Two users live: primary(email,5) + builder(digest,8). Verified: independent selection
  + sent-isolation (marking builder sent didn't touch primary). Added Builder Radar sources (Azure SDK,
  openai-python, LangGraph, Agent Framework, Pydantic AI, MCP spec releases) for the builder.
  KNOWN TRADEOFF (accepted): shared 'how to USE AI' prompt down-rates SDK/library releases (~0-10), so
  builder content diverges only as feedback accumulates (cold-start). Escape hatch if too weak = optional
  per-user SOURCE filter (not a prompt). No long-term builder memory by design: read digest, act (commit
  = record), ignore next cycle.
- IaC DONE (2026-06-16): infra/main.bicep + main.bicepparam capture every Azure resource +
  passwordless role assignments (resource-group scoped, parameterized). what-if verified: 11
  core resources match live exactly. Source of truth going forward — new resources land here.
