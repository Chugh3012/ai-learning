# Long-Term Vision And Production Plan

This document consolidates the original long-term production plan with the later deep-research
report. It is intended to be the durable operating guide for the project: a product vision,
architecture target, security posture, personalization roadmap, and productionization plan.

The most important shift is this:

> The future asset is not one AI newsletter, one website, or one pipeline. The future asset is a
> topic-neutral intelligence platform that turns trusted content and user signals into safe,
> personalized, multi-surface learning experiences.

AI is the first domain. The platform should be able to support other domains later without
rewriting the engine.

## Executive Summary

The current product scans AI/LLM sources, ranks them, personalizes per profile, delivers concise
editions, and learns from feedback. That is already a strong foundation. The long-term opportunity
is to grow it into a reusable intelligence layer that can power multiple publications, topics,
websites, internal workflows, and eventually team or organization use.

The long-term north star:

> Build a topic-neutral intelligence platform that finds high-signal knowledge, explains why it
> matters, learns each reader's taste, and helps them act, with security and operational
> reliability treated as product features rather than afterthoughts.

The project should evolve around five durable principles:

- **Neutral core:** AI is one topic pack, not the permanent boundary of the engine.
- **Strict security:** every public endpoint, AI layer, dependency, and workflow is treated as
  hostile until proven safe.
- **Measured intelligence:** every ranking, prompt, model, personalization, and policy change has
  evaluation and rollback.
- **Many experiences:** websites, emails, APIs, admin tools, team digests, and builder workflows
  should all use the same intelligence layer.
- **Owned memory:** content, feedback, profiles, evaluation data, and generated artifacts should
  remain portable and recoverable.

The immediate production priority is not another flashy feature. It is hardening: unsubscribe,
token expiry, rate limiting, SSRF protection, storage key lockdown, stricter CI gates, backups,
restore drills, observability, and source-quality metrics.

## What This Project Is Becoming

Today:

- Public brand: **Chugh Vibes**
- Current vertical: AI/LLM signal brief
- Internal package: `ai_scout`
- Core loop: ingest, rank, embed, select, brief, deliver, feedback

Long term:

- Public brands can vary by publication or topic.
- AI becomes one topic pack.
- The core package should become topic-neutral.
- The reusable asset is the intelligence platform: content graph, ranking, personalization,
  policy, evaluation, delivery, and feedback.

The strongest product description:

> A personal signal system that reads trusted sources, filters noise, teaches the reader what
> matters, and compounds from their feedback.

The strongest platform description:

> A topic-neutral intelligence layer for creating safe, personalized learning and briefing
> experiences across many domains.

## Naming And Scope

Do not rush a public rename. But do stop adding hard-coded AI assumptions to reusable layers.

Recommended naming model:

- **Engine / library:** `signal_scout`, `scout_core`, `briefing_engine`, or `intelligence_core`
- **Current vertical:** AI Scout
- **Public publication:** Chugh Vibes
- **Future verticals:** topic packs or publications using the same engine

Safe internal abstractions:

- `topic`
- `source`
- `content_unit` or `item`
- `topic_pack`
- `profile`
- `lens`
- `interaction_event`
- `signal`
- `recommendation`
- `brief`
- `edition`
- `delivery`
- `feedback`
- `policy_decision`
- `evaluation_run`

Avoid new reusable names like:

- `ai_item`
- `ai_user`
- `ai_topic`
- `llm_profile`
- `ai_rank`
- AI-specific table names outside the AI topic pack

Practical rule: "AI" should appear in public copy, AI topic config, AI ranking rubrics, AI eval
datasets, and AI-specific profiles. It should not leak into core storage, service contracts, or
platform abstractions unless there is no reasonable generic concept.

## Product Pillars

### 1. Signal Over Volume

The product should never become another inbox firehose. The default promise is few, useful,
explained.

Product behavior:

- Deliver fewer items rather than weaker items.
- Prefer "why this matters" over plain summaries.
- Group duplicates and repeated stories.
- Surface trend shifts, not every mention.
- Track source quality and remove low-yield sources.

### 2. Personalized Learning, Not Just Personalized Links

The long-term product is not RSS plus ranking. It should help the reader learn and act.

Product behavior:

- Each card has a lesson, reason, and action.
- Saved items become a personal library.
- "Try this" actions become an experiment queue.
- Weekly recaps synthesize themes and behavior.
- Feedback teaches the system what to send next.

### 3. Trust And Control

Readers should understand and control the system.

Product behavior:

- One-click unsubscribe and pause.
- Preference center for interests, cadence, edition size, and novelty.
- Transparent "why this was picked" explanations.
- No dark patterns around subscription or confirmation.
- Clear data retention and deletion story.

### 4. Durable Ownership

The knowledge base and feedback loop should remain portable. Cloud services can be swapped, but
the core data and logic should stay ours.

Product behavior:

- SQLite remains the owned local system of record until scale demands a change.
- Azure Blob remains backup/distribution, not the source of truth.
- Tables hold operational subscriber/feedback state.
- Every external service has a graceful degradation path.

### 5. Platform Leverage

Many experiences should reuse one intelligence layer.

Product behavior:

- The same profile and feedback can inform email, web, API, and builder experiences.
- A future topic should not fork the pipeline.
- New delivery channels should be sinks, not new products.
- New ranking rubrics should be topic-pack assets, not service rewrites.

## Topic-Neutral Platform Model

The next major architecture evolution is to separate the generic briefing engine from
topic-specific packs.

### Topic Pack

A topic pack contains:

- Source list.
- Topic taxonomy.
- Ranking rubric.
- Brief style.
- Evaluation golden set.
- Safety/quality exclusions.
- Default profiles and interests.
- Public copy, if the topic has a landing page.
- Optional assessments or exercises if the topic becomes course-like.

Example:

```text
topics/
  ai/
    sources.opml
    tags.json
    rank_rubric.md
    eval.jsonl
    public_copy.json
  startups/
    sources.opml
    tags.json
    rank_rubric.md
    eval.jsonl
  engineering/
    sources.opml
    tags.json
    rank_rubric.md
    eval.jsonl
```

The current `config/` directory can remain as the active AI topic for now. When the second topic is
real, migrate toward `topics/<topic_id>/` and add `topic_id` to sources, items, profiles, metrics,
and editions.

### Durable Concepts

These concepts should remain stable even if the topic changes:

- **Topic:** the domain being covered.
- **Content unit:** an article, post, paper, release note, video, lesson, or internal note.
- **Source:** where content units come from.
- **Skill / competency:** optional, for learning-oriented domains.
- **Assessment:** optional, for practice or mastery tracking.
- **Learner or reader profile:** declared preferences and inferred taste.
- **Interaction event:** impression, click, save, vote, skip, completion, retry, dwell.
- **Recommendation:** an item selected for a profile and reason.
- **Policy decision:** whether an action, output, or data access is allowed.
- **Edition:** the packaged delivery for a profile at a point in time.

### Data Model Direction

Current model is close to generic. To support multiple topics cleanly, plan for:

- `source.topic_id`
- `item.topic_id`
- `profile.topic_id`
- `signal.kind` remains namespaced, but lens should include topic if needed
- `tag` becomes topic-pack-specific
- ranking signal can become `relevance:<topic_id>` if items can cross topics
- evaluation results include topic, rubric version, model, prompt version, and dataset version

Do not fork the whole app per topic. Fork only topic packs and public surfaces.

### Ranking Generalization

The ranking prompt should become topic-configurable:

- Generic system: "rank for signal, novelty, usefulness, trust."
- Topic rubric: "for AI, reward workflows/tools/model shifts..."
- Exclusion rubric: "for AI, demote non-AI, pure PR..."
- Safety rubric: "avoid unsafe or misleading items for this topic."

This prevents AI assumptions from leaking into startup, policy, engineering, investing, or health
research editions.

## Target Architecture

The stable production shape today:

```text
Sources -> Ingest -> Owned KB -> Rank -> Embed -> Select -> Brief -> Deliver
                                      ^                         |
                                      |                         v
                                Feedback <---------------- Subscribe/Web
```

The long-term platform shape:

```mermaid
flowchart LR
  subgraph Experiences
    A[AI publication]
    B[Future topic websites]
    C[Email and digests]
    D[Public API and partner surfaces]
    E[Internal authoring/admin tools]
    F[Builder automation]
  end

  subgraph Intelligence Layer
    G[Model gateway]
    H[Retrieval and ranking]
    I[Policy and safety]
    J[Personalization]
    K[Evaluation and experiments]
    L[Brief generation]
  end

  subgraph Data and Platform Layer
    M[Topic packs and content graph]
    N[Profile and event store]
    O[Feature store]
    P[Batch and real-time pipelines]
    Q[Observability and audit logs]
  end

  Experiences --> Intelligence Layer
  Intelligence Layer --> Data and Platform Layer
```

### Core Components

Current and near-term:

- **Static Web App:** public landing page and subscription UI.
- **Azure Function:** subscribe, confirm, unsubscribe, feedback capture.
- **Azure Tables:** subscribers, profiles, feedback tokens, feedback events, cached editions.
- **SQLite KB:** source/item/tag/signal/embedding/draft equivalent owned store.
- **Azure Blob:** KB backup, digests, generated artifacts.
- **Foundry/OpenAI deployments:** ranking, lesson generation, embeddings.
- **GitHub Actions:** scheduled pipeline, PR gate, builder automation.
- **Azure Monitor/Grafana:** metrics and operational dashboards.

Future logical services:

- **Model gateway:** abstracts providers and model routing by cost, latency, capability, and eval
  results.
- **Retrieval/ranking service:** owns search, deduplication, novelty, source quality, and next-best
  item decisions.
- **Policy/safety service:** enforces permissions, PII rules, approval requirements, and output
  safety.
- **Personalization service:** stores profile summaries, taste vectors, learning state, and
  exploration policy.
- **Evaluation/experiment service:** gates prompts, models, rankers, and personalization changes.
- **Event pipeline:** captures impressions, deliveries, clicks, saves, votes, skips, completions,
  and errors.
- **Feature store:** materializes consistent online/offline features once ML complexity justifies it.

### Production Boundaries

Keep the app split into these layers:

- **Domain:** pure models and rules.
- **Repositories:** storage access and migrations.
- **Services:** ingest, rank, embed, select, feedback, delivery.
- **Interfaces:** CLI, Function routes, web.
- **Topic packs:** configuration and rubrics.
- **Policy:** deterministic authorization/safety decisions.
- **Evaluation:** datasets, metrics, thresholds, and result artifacts.

No service should directly know about Azure unless it is an infrastructure repository or delivery
sink. No domain model should import cloud SDKs.

### Repo Strategy

Stay in a modular monorepo while the project is small. This keeps schemas, tests, evals, workflows,
and infrastructure in one governed place.

Consider a software catalog later, such as a Backstage-style catalog, only when there are enough
services, owners, APIs, and environments that discovery becomes painful.

Recommended future package boundaries:

```text
packages/
  core/
  topic-schema/
  policy/
  personalization/
  evaluation/
  delivery/
topics/
  ai/
  startups/
apps/
  web/
  function/
  admin/
```

Do not split services purely for aesthetic reasons. Split when scaling, ownership, security, or
deployment cadence demands it.

## Standards And Reference Patterns

Use established standards as pressure rails, not bureaucracy.

Useful reference patterns:

- **Twelve-Factor App:** explicit dependencies, config in environment, portability.
- **OpenFeature:** vendor-neutral feature flags and experiments.
- **MCP:** standardized tool/data connectivity for AI agents and external capabilities.
- **OpenTelemetry:** vendor-neutral traces, metrics, and logs.
- **SRE golden signals:** latency, traffic, errors, saturation.
- **Error budgets:** balance innovation and reliability.
- **NIST AI RMF:** AI risk as lifecycle management.
- **NIST Privacy Framework:** privacy risk and data minimization.
- **NIST SSDF:** secure software development.
- **CISA Secure by Design / Secure by Default:** security as a manufacturer responsibility.
- **OWASP ASVS:** web application security controls.
- **OWASP LLM guidance:** prompt injection, insecure output handling, model denial of service,
  supply-chain risks, and agent/tool risks.
- **SLSA / Sigstore / artifact attestations:** supply-chain provenance and artifact integrity.
- **SBOM / AI BOM:** inventory software and AI ingredients.
- **MLflow:** experiment tracking, model evaluation, model lifecycle.
- **Feast:** feature store when online/offline feature consistency becomes important.
- **Airflow or equivalent:** code-defined data pipelines if the batch graph grows.

Adopt incrementally. Do not introduce heavyweight infrastructure before there is a real operational
need.

## Security Philosophy

"No security vulnerabilities ever" is the right ambition but not a credible literal promise. The
production goal is stronger and more actionable:

- No known vulnerable configuration.
- Minimal public attack surface.
- Least-privilege identity everywhere.
- No secrets in code, config, logs, generated artifacts, or committed files.
- Every public input validated, rate-limited, and observable.
- Every AI-generated output treated as untrusted until rendered safely.
- Every privileged action behind deterministic policy.
- Every release gated by tests, security checks, and rollback.
- Every incident containable.

Security must be a release gate, not a clean-up task.

### The Model Is Never A Trusted Principal

The model is an untrusted reasoning component operating inside a controlled system. It should never
be treated as an authenticated actor.

Rules:

- Model output cannot directly authorize data access.
- Model output cannot directly perform write/admin actions.
- Tool access is allowlisted and scoped.
- Sensitive actions require deterministic policy checks.
- High-impact actions require human approval.
- All model-mediated actions are audited.
- Source content is untrusted input.
- Retrieved context is untrusted input.
- Generated output is untrusted text.

Suggested trust tiers:

| Tier | Examples | Required controls |
|---|---|---|
| Public read | Static content, public sources | Input validation, escaping, rate limits |
| Internal read | KB, profiles, metrics | Auth, scoped identity, audit |
| Low-risk write | Save, vote, subscribe confirmation | Token TTL, rate limits, idempotency |
| Medium-risk write | Profile changes, source proposals | Auth, policy, audit, rollback |
| High-risk write | Sending bulk email, publishing, PR merge, admin actions | Human approval, policy, audit, staged rollout |

## Threat Model

| Threat | Risk | Required Control |
|---|---|---|
| Subscription spam / email bombing | Public endpoint can be abused to send confirmation emails | Rate limit by IP/email hash, resend cooldown, honeypot, optional CAPTCHA/proof-of-work if abused |
| Token replay | Old feedback or confirmation links can be reused | TTL on tokens, consume or rotate sensitive tokens, store `expiresTs`, reject stale tokens |
| Missing unsubscribe | Compliance/trust failure | One-click unsubscribe route, unsubscribe link in every email, status changes to `unsubscribed` |
| Open redirect | Feedback click redirects to attacker-controlled URLs | Only redirect to URL stored at token mint time; validate scheme; consider source-domain allowlist |
| SSRF via article fetch | Feed item URL may point to internal/private address | Block private IP ranges, localhost, metadata endpoints, non-http schemes; optionally fetch through allowlisted egress |
| Prompt injection from feed content | Malicious article tries to alter model behavior | Treat source text as data; strict system prompts; schema validation; no tool use from source content |
| Insecure model output handling | Model output injects unsafe HTML, links, or commands | Escape templates, validate URLs, never execute model text |
| Model denial of service | Expensive prompts or large inputs drive cost/latency | Input caps, batching limits, cost budgets, timeouts |
| Data poisoning | Bad sources or feedback manipulate rankings | Source quality scores, anomaly detection, human review for new sources |
| HTML injection | Feed title/summary or model output rendered in email/web | Escape all templates by default; never mark model text safe |
| Secret leakage | Env/config accidentally logged or committed | `.env` ignored, no keys, OIDC, secret scanning, no full env dumps |
| Excessive permissions | Compromise of Function/GitHub identity has broad access | Split identities by purpose; least-privilege RBAC; avoid storage account keys |
| Supply-chain dependency issue | Python/Actions package compromise | Pin critical action SHAs, Dependabot/Renovate, audit dependencies, SBOMs, attestations |
| Cost abuse | Public endpoints or model calls drive spend | No model calls from unauthenticated routes; daily cost budgets; model-call caps |
| Data loss | KB corruption or accidental overwrite | Blob versioning, periodic snapshots, restore drill, migration tests |
| Cross-user leakage | One user receives another user's digest or feedback | Lens-scoped signals, tests for profile isolation, no global default email fallback |
| Malicious automation PR | Builder workflow proposes unsafe changes | Draft PRs only, protected files, required review, CI gates, threat detection |

## Security Baseline

High priority:

- Add `allowSharedKeyAccess: false` to every storage account.
- Add unsubscribe route and email footer link.
- Add token expiry for confirm and feedback tokens.
- Add SSRF protection before fetching full article text.
- Add public endpoint rate limiting.
- Make CI fail if security-critical environment or eval config is missing.
- Add dependency scanning and action pinning policy.
- Enable branch protection, required reviews, and required checks on `main`.
- Enable secret scanning with push protection.
- Enable code scanning.
- Keep GitHub OIDC for short-lived cloud credentials; avoid long-lived cloud secrets.

Medium priority:

- Generate SBOMs for releasable artifacts.
- Add artifact attestations in CI.
- Sign release artifacts or containers with Sigstore or equivalent.
- Separate storage accounts or identities for subscribers, feedback, and KB if blast radius grows.
- Add signed internal API for admin/profile changes.
- Add audit table for subscription/profile status changes.
- Add periodic privacy export/delete path.
- Add WAF/front-door only if traffic or abuse justifies it.

Vulnerability management:

- Do not rely on one vulnerability feed.
- Watch Dependabot/GitHub alerts, vendor advisories, CISA KEV, and internal exploitability.
- Prioritize reachable and exploited vulnerabilities before abstract CVSS alone.
- Patch critical internet-facing dependency issues quickly.
- Track security exceptions with owners and expiry dates.

## Privacy And Data Governance

The product will hold email addresses, names, preferences, feedback, saved items, and reading
behavior. Treat that as sensitive product data even if it is not a password or payment record.

Principles:

- Collect only what improves delivery.
- Store opaque user IDs in product logic.
- Keep email as operational contact data, not as a primary key in the KB.
- Hash email for table keys.
- Support unsubscribe and deletion.
- Define retention windows.
- Avoid logging email addresses, tokens, or full personal profiles.
- Do not infer sensitive traits.
- Give users control over explicit preferences.
- Provide a neutral/non-personalized mode if personalization grows more sophisticated.

Recommended retention:

- Pending subscription rows: delete after 7 days.
- Confirmation tokens: expire after 24-72 hours.
- Feedback tokens: expire after 30-90 days.
- Feedback events: keep while useful for personalization, then aggregate.
- Raw generated digests: keep latest N or last 90 days unless saved.
- Metrics: keep 90-180 days.
- Audit events: keep long enough to investigate abuse and compliance issues.

If the product later targets schools, children, or formal education workflows, pause and get legal
review before collecting learner data. FERPA/COPPA-like obligations may apply depending on users,
jurisdiction, and data collected.

## Reliability And Operations

Production readiness means the project can run unattended and explain itself when something goes
wrong.

### Service-Level Targets

Initial targets:

- Daily pipeline succeeds at least 95% of days.
- No duplicate delivery to the same profile for the same item.
- No email sent to unsubscribed users.
- Ranking/eval gate runs on every PR that changes ranking or selection.
- Restore KB from backup within 30 minutes.
- Public subscribe/confirm/feedback endpoints return useful errors, not stack traces.
- Public endpoints have bounded latency and predictable failure modes.

Future SLOs:

- Subscribe endpoint availability.
- Confirm endpoint availability.
- Daily delivery completion.
- Ranking eval pass rate.
- Mean delivery latency from scheduled start.
- Error-budget burn for public endpoints.

### Observability

At minimum, metrics should answer:

- Did ingest run?
- How many sources failed?
- How many new items arrived?
- How many items were ranked/embedded?
- What did ranking cost?
- How many users/profiles were due?
- How many editions were delivered?
- How many clicks/saves/votes happened?
- Which sources are high or low yield?
- Did eval quality change?
- Which model/prompt/rubric versions were used?

Add dashboards:

- Pipeline health.
- Delivery health.
- Source quality.
- User engagement.
- Ranking quality and cost.
- Security/abuse signals.
- Model usage and cost.
- Evaluation history.

Alert on:

- No successful sync in 36 hours.
- Source failure rate above threshold.
- Delivery failures above threshold.
- Subscribe errors spike.
- Feedback token lookup failures spike.
- Cost exceeds daily/weekly budget.
- Eval gate fails or is skipped in CI.
- Public endpoint 5xx rate spikes.
- Confirmation email send failures spike.

Instrumentation direction:

- Use structured logs.
- Add request IDs and run IDs.
- Add model/prompt/rubric version IDs to AI calls.
- Adopt OpenTelemetry if the system becomes multi-service.
- Track SRE golden signals: latency, traffic, errors, saturation.
- Use error budgets to decide when to slow feature work and fix reliability.

### Backups And Recovery

Required:

- Blob versioning for KB backups.
- Daily KB snapshot with timestamp, not only overwrite.
- Restore command documented and tested.
- Migration tests for old schemas.
- Local dry-run path that never uploads.

Disaster drill:

1. Create a fresh environment.
2. Restore latest KB.
3. Run sync with `--no-upload`.
4. Produce one test digest.
5. Verify subscriber table is not overwritten.
6. Verify an unsubscribed user remains unsubscribed.

## Quality Gates

Every PR should pass:

- Compile all package, builder, and Function code.
- Offline unit tests.
- Ranking eval when ranking/prompt/model changes.
- Security smoke checks for public routes.
- Infrastructure compile/what-if for Bicep changes.
- Web build/static validation if web changes.

Recommended future gates:

- Type checking.
- Linting.
- Dependency vulnerability audit.
- Secret scan.
- Code scanning.
- HTML/email snapshot rendering tests.
- Golden-output tests for brief templates.
- Prompt regression tests for summarization and explanations.
- Prompt-injection tests for AI layers.
- Contract tests for public routes.
- Source-fetch SSRF tests.
- Artifact attestations for releases.
- SBOM generation.

Release promotion path:

1. Unit tests.
2. Contract tests.
3. Static analysis.
4. Dependency/security review.
5. Secret scan.
6. Prompt/ranking/safety evals.
7. Offline recommendation evaluation.
8. Canary or limited rollout.
9. Gradual rollout behind feature flags.
10. Observability review.

Feature flags should be vendor-neutral if they become important. OpenFeature is a good long-term
shape because it avoids binding product logic to one flag provider.

## AI And ML Roadmap

The system already uses AI for relevance scoring, embeddings, and lesson generation. The next
frontier is deeper personalization and product intelligence.

### Current Personalization

- Shared relevance score.
- Interest sentence embedding.
- Per-lens affinity from feedback.
- Exploration slot to avoid filter bubbles.
- Past-item connection using embeddings.

### Personalization Beyond The Chatbot Layer

Personalization should not be added only as a chatbot. It should operate across:

- **Ranking layer:** what content gets selected.
- **Curriculum layer:** what sequence of ideas or skills comes next.
- **Generation layer:** tone, depth, analogies, hints, examples.
- **Retention layer:** review timing, reminders, recaps, streak recovery.
- **Safety layer:** when to simplify, warn, slow down, or refuse.
- **Authoring layer:** what source/topic gaps editors should fill.

Start with behavioral intelligence, not sensitive profile inference. Use observed learning and
preference signals:

- impressions
- clicks
- saves
- votes
- skips
- dwell time
- completions
- retries
- "tried this"
- "useful / not useful"
- explicit preferences

Do not personalize from sensitive categories unless there is a clear legal, ethical, and product
basis.

### Next Personalization Layers

1. **Reason Codes**
   - Generate structured reasons for each pick: topic match, source quality, novelty, saved-item
     similarity, trend relevance.
   - Show these in the brief and store them for analysis.

2. **User Taste Model**
   - Maintain per-lens vectors for liked, saved, skipped, and clicked items.
   - Use recency weighting.
   - Keep explicit user interest text as a steering layer, not the whole profile.

3. **Source Quality Model**
   - Score each source by high-ranked rate, delivered rate, click/save rate, and empty-feed rate.
   - Use it to prune noisy sources and boost reliable sources.

4. **Novelty Model**
   - Penalize repeated stories across sources and days.
   - Reward genuinely new themes for each profile.
   - Detect "same announcement, better explanation" separately from duplicates.

5. **Topic Trend Detection**
   - Cluster recent items.
   - Detect rising clusters and week-over-week changes.
   - Include "topic radar" in weekly editions.

6. **Experiment Queue**
   - Extract actions from cards.
   - Let users mark tried/useful/not useful.
   - Feed that back into ranking as stronger signal than clicks.

7. **Bandit-Based Exploration**
   - Replace fixed `explore_ratio` with a contextual bandit once there is enough feedback.
   - Optimize for saves/positive votes, not clicks alone.

8. **Learning Recaps**
   - Weekly model-generated synthesis from delivered + saved + skipped items.
   - Include "what the system learned about you."

9. **Knowledge Tracing / Learning State**
   - If the product becomes course-like, track skill mastery over time.
   - Start simple with heuristics; only add Bayesian/deep knowledge tracing once there are enough
     assessments and interactions.

10. **Learning-To-Rank**
    - Train or tune rankers when there is enough labeled behavior.
    - Keep offline evals and online experiments separate.

11. **Topic-Specific Models**
    - Keep one generic engine.
    - Use separate rubrics/evals per topic.
    - Only fine-tune when there is enough labeled data and clear measurable gain.

### ML Platform Direction

Do not introduce ML infrastructure before it has a job. The likely path is:

1. Current heuristics plus embeddings.
2. Better event logging.
3. Profile/taste summaries.
4. Offline evaluation datasets.
5. Feature tables/materialized features.
6. Learning-to-rank or bandit experiments.
7. Feature store if online/offline consistency becomes painful.
8. MLflow-style experiment tracking once model experiments multiply.

Keep advanced ML behind product metrics:

- save rate
- positive vote rate
- unsubscribe rate
- return rate
- source quality
- weekly engagement
- explicit usefulness
- eval pass rate

Do not add personalization complexity unless it improves measurable outcomes.

### AI Safety Rules

- Source content is untrusted data.
- Model output is untrusted text.
- Do not let model output call tools or mutate state without deterministic validation.
- Store structured model output only after schema validation.
- Keep prompts and eval datasets versioned.
- Every AI layer needs an offline fallback.
- Model and prompt changes require evaluation.
- Tool-using agents require policy enforcement and audit.

## Peer Product Lessons

Useful patterns from mature learning/personalization products:

- **Duolingo:** personalization is infrastructure, not UI decoration. Difficulty and next-item
  choice are modeled underneath the lesson experience.
- **Khan Academy / Khanmigo:** trusted grounding and visible safety posture matter more than a
  general chatbot bolted onto content.
- **Coursera Coach:** AI should support the instructional workflow, including authors and teachers,
  not just the learner-facing page.
- **Quizlet Q-Chat:** adaptive tutoring works best when coupled with an owned corpus of study
  material.

Shared pattern:

> Owned content + behavior data + personalization + guardrails + workflow integration.

For this project, the equivalent moat is:

- topic taxonomies
- source quality history
- delivered/saved/skipped behavior
- profile/lens memory
- eval datasets
- rubric versions
- trusted brief generation
- safe operational workflows

## Product Roadmap

### Phase 0: Production Hardening

Goal: safe, reliable single-topic public product.

Deliver:

- One-click unsubscribe.
- Token TTL and cleanup.
- Rate limiting / abuse guard for subscribe.
- Storage shared-key disabled everywhere.
- SSRF protection for full-text fetch.
- CI eval missing-config failure in CI.
- KB snapshots and restore drill.
- Metrics dashboard and basic alerts.
- Public API CORS/config cleanup.
- Email footer with unsubscribe and preference links.

Exit criteria:

- No known high-risk public endpoint issues.
- A new user can subscribe, confirm, receive welcome, give feedback, unsubscribe.
- Daily run can fail gracefully and recover next day.
- Backups can be restored into a fresh environment.

### Phase 1: Better Reader Value

Goal: make every edition feel useful and memorable.

Deliver:

- "Why this was picked."
- Saved library.
- Weekly recap.
- Preference center.
- Source quality dashboard.
- Topic radar in digest.
- Similar-story bundle selection.

Exit criteria:

- Users can tune their edition without code/config edits.
- Saved items become durable product value.
- Source pruning decisions are data-backed.

### Phase 2: Multi-Topic Engine

Goal: support more topics without cloning the app.

Deliver:

- Topic pack directory.
- `topic_id` in source/item/profile flow.
- Per-topic ranking rubrics.
- Per-topic eval datasets.
- Public copy per publication.
- Migration path from current AI config.
- Topic-neutral package names or compatibility wrapper.

Exit criteria:

- Add a second topic by adding a topic pack, not rewriting services.
- AI topic continues to work unchanged.
- Metrics can segment by topic.

### Phase 3: Advanced Personalization

Goal: turn feedback into a real learning system.

Deliver:

- User taste vectors.
- Recency-weighted feedback.
- Novelty scoring.
- Contextual exploration.
- Experiment queue.
- Personalized weekly synthesis.
- Profile explanation and correction UI.

Exit criteria:

- Personalization improves measured save/vote rate.
- Users can see and correct what the system believes about them.
- Exploration improves discovery without hurting unsubscribe/negative-feedback rates.

### Phase 4: Intelligence Platform

Goal: make the intelligence layer reusable across surfaces.

Deliver:

- Model gateway.
- Policy/safety service or module.
- Evaluation/experiment service or module.
- Event schema and event pipeline.
- Versioned prompt/rubric contracts.
- Feature flags/canary releases.
- Internal authoring/admin tools.

Exit criteria:

- Multiple experiences can use the same ranking, profile, policy, and evaluation layers.
- Model or prompt changes can be evaluated and rolled out gradually.

### Phase 5: Team / Organization Use

Goal: make the engine useful for small teams and private knowledge.

Deliver:

- Team profiles.
- Shared saved library.
- Topic channels.
- Admin dashboard.
- Private sources.
- Role-based access.
- Export to Slack/Teams/Notion/GitHub issues.
- Organization-level policy controls.

Exit criteria:

- One deployment can serve multiple users and teams without cross-user leakage.
- Team admins can manage sources, profiles, and delivery safely.

## Production Operating Model

Production needs an operating model, not only code.

Required practices:

- Version API contracts.
- Version event schemas.
- Version prompt and rubric schemas.
- Version topic packs.
- Keep architecture decision records for durable choices.
- Define owners for services, workflows, and data tables.
- Define a deprecation policy for fields, prompts, endpoints, and topics.
- Keep runbooks for deploy, rollback, restore, and incident response.
- Make metrics part of each feature's definition of done.

Environment strategy:

- Local: no cloud writes by default.
- Staging: realistic infra, test identities, no real subscribers.
- Production: protected branch, required checks, approved deployments.

Configuration strategy:

- Config in environment or topic packs.
- No secrets in config.
- Defaults are safe.
- Missing production-critical config fails loudly in CI/production.
- Local developer convenience never weakens production gates.

## Definition Of Production Ready

A feature is production-ready only when:

- It has a clear user outcome.
- It fails safely.
- It is observable.
- It is covered by tests at its deterministic core.
- It has abuse/security considerations documented.
- It does not require secrets in code or local state.
- It can be disabled or rolled back.
- It does not couple the core engine to one topic unless it is explicitly topic-pack code.
- It has an owner.
- It has a migration/cleanup story if it adds data.
- It has a metric that can tell whether it helped.

## Immediate Decisions To Make

1. Decide whether the reusable engine will remain named `ai_scout` internally until the second
   topic exists, or whether to rename early to a topic-neutral package.
2. Decide the first non-AI topic candidate before designing topic packs too abstractly.
3. Decide whether the product is primarily a personal publication, a reusable library, or a future
   hosted service. The architecture can support all three, but prioritization differs.
4. Decide minimum privacy posture before inviting broader users.
5. Decide whether admin/profile management stays table-driven for now or needs a small private UI.
6. Decide whether feature flags are needed now or only once there are multiple user-facing
   experiments.
7. Decide what the first formal SLO should be: daily delivery, subscribe flow, or ranking gate.

## Recommended Next Actions

1. Ship production hardening first: unsubscribe, token TTL, rate limiting, SSRF guard, storage key
   lockdown, CI eval strictness.
2. Add source quality dashboard because it improves the whole pipeline.
3. Add saved library and weekly recap because they turn one-off emails into compounding value.
4. Start extracting topic assumptions from prompts/config into an explicit AI topic pack.
5. Add reason codes so personalization becomes visible and debuggable.
6. Add event schema/versioning before advanced personalization.
7. Keep advanced ML behind metrics: do not add personalization complexity unless it improves saves,
   positive votes, retention, or explicit usefulness.
8. Keep the generated deep-research report as raw input, but treat this document as the consolidated
   operating plan.

## Practical Mantra

> Neutral core, strict security, measured intelligence, many experiences.

If the project follows that standard, the current AI-learning product can become the first
successful surface on top of a much more durable intelligence platform.

