# ai-scout — repository brief for AI coding agents

You may be the **GitHub Copilot coding agent** invoked from a "🤖 Builder radar" issue — in that
case you are *user 2* of this app (the builder), acting on items the pipeline surfaced as relevant
to building/operating it.

## Non-negotiable principles (a PR that breaks these will be rejected)
- **Passwordless / Entra-first.** All Azure access uses `DefaultAzureCredential` (OIDC in CI,
  `az login` locally). NO keys, connection strings, account secrets, or SAS in code or config.
- **Infra-as-Code first.** `infra/main.bicep` is the source of truth for every Azure resource.
  If a change needs infra, edit the Bicep — never hand-provision as the source of truth.
- **The eval-gate must stay green.** `.github/workflows/pr-gate.yml` grades ranking quality on a
  labeled golden set (plus a compile check and the offline unit tests in `tests/`) on EVERY PR and
  is the **merge authority** — a PR auto-merges only when this gate is green. Don't regress it.
- **Config over code.** Growth = add a row to a JSON/OPML/YAML config, not a new code path.
  Sources → `config/sources.opml`. Users → `config/users.json`. Tags → `config/tags.json`.
- **Sleek, no bloat.** Revise files in place; don't append duplicate logic or scaffold unused
  abstractions. Don't add markdown docs or code comments unless asked. One focused PR per change.
- **Every stage is optional + graceful.** Ranking/draft/email/feedback each no-op (never crash
  the pipeline) when their backing service is unconfigured.

## How to work a "Builder radar" issue
1. Each listed item is a candidate improvement (an SDK change to adapt to, a dep upgrade, an
   agent/eval/RAG technique). For genuinely useful ones, make the change in a focused PR.
2. **Not every item warrants action — "no change" is a valid outcome.** Don't force PRs.
3. Respect every principle above. If infra changes, update `infra/main.bicep`. Run/keep the
   eval-gate green. Prefer config edits over new code.
4. Open a PR for human review. **Do NOT merge to `main`.** Whether your PR is merged or closed
   is itself the feedback signal — make each PR genuinely worth merging.
