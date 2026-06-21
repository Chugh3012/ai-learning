---
# Builder Radar — the app's 2nd user (the agent maintaining it) improves the repo.
# Built on GitHub Agentic Workflows (gh-aw) — NOT hand-rolled. The agent runs read-only by
# default and may ONLY open a DRAFT pull request (safe-output). It never merges; a human marks
# ready/merges — which is also the strongest feedback signal. Compile with: gh aw compile.
on:
  # Cost-conscious cadence: run twice a week (Mon + Thu) rather than after every daily
  # kb-sync — genuinely actionable items are rare, and each run spends Copilot premium
  # requests. kb-sync runs ~01:30 UTC daily, so by 06:00 the day's builder digest is already
  # in Blob. Manual dispatch stays available for on-demand runs.
  schedule:
    - cron: "0 6 * * 1,4"
  workflow_dispatch: {}

# The builder is a USER: it READS its digest that kb-sync already produced and published to Blob
# (builder/inbox.py), then REACTS to it (builder/review.py votes keep/skip — like starring email),
# exactly like the human reads and triages their top-5. It never runs the engine: no
# fetch/rank/embed/deliver, no KB access. kb-sync (which this triggers off) did all that once.
steps:
  - name: Set up Python
    uses: actions/setup-python@v6
    with:
      python-version: "3.13"
  - name: Azure login (OIDC, passwordless)
    uses: azure/login@v2
    with:
      client-id: ${{ vars.AZURE_CLIENT_ID }}
      tenant-id: ${{ vars.AZURE_TENANT_ID }}
      subscription-id: ${{ vars.AZURE_SUBSCRIPTION_ID }}
  - name: Read & react to builder digest (consumer only — never the engine)
    env:
      STORAGE_ACCOUNT: ${{ vars.STORAGE_ACCOUNT }}
      BLOB_CONTAINER: ${{ vars.BLOB_CONTAINER }}
      FOUNDRY_PROJECT_ENDPOINT: ${{ vars.FOUNDRY_PROJECT_ENDPOINT }}
      FOUNDRY_MODEL_NAME: ${{ vars.FOUNDRY_MODEL_NAME }}
      FEEDBACK_STORAGE: ${{ vars.FEEDBACK_STORAGE }}
    run: |
      pip install -r requirements.txt
      python builder/inbox.py builder    # read its delivery from Blob (resolved by role)
      python builder/review.py builder   # react: vote keep/skip on the digest
      echo "--- builder digest ---"
      cat digests/*.md 2>/dev/null | tail -n +1 || echo "(no builder digest today)"

permissions:
  contents: read
  pull-requests: read
  issues: read
  id-token: write   # OIDC -> Azure (Blob, Foundry, feedback) in the deterministic pre-step

network:
  allowed:
    - defaults
    - python

tools:
  github:
  bash: true
  web-fetch:

safe-outputs:
  create-pull-request:
    draft: true
    title-prefix: "[builder-radar] "
    labels: [automation, builder-radar]
    max: 1
  create-issue:
    title-prefix: "[builder-radar] "
    labels: [automation, builder-radar]
    max: 1
---

# Builder Radar

You are the builder of **ai-scout** (this repo), acting as its 2nd user. First read
`.github/copilot-instructions.md` for the non-negotiable principles.

A deterministic pre-step has generated today's **builder digest** at `digests/*.md` —
external AI/SDK/agent/eval news ranked for engineering relevance to THIS codebase and reordered
by past builder feedback. Each item has a numeric id; the file ends with `<!-- items: <ids> -->`.

## Your job — selective, but act when there's a real win
1. Read the digest. **Decide which items (if any) are genuinely worth acting on** for this repo.
   You are looking for a *concrete, minimal* improvement you can land today, such as:
   a breaking SDK change to adapt to; a ranking/eval/RAG/agent technique from an item that you can
   apply to our `Ranker`, `RankEvaluator`, `Selector`, or prompts; a small config tune
   (`config/*.json`, `sources.opml`); or a focused fix. Routine dependency/action version bumps are
   handled automatically by Dependabot — don't open those.
2. If one is worth it, make **ONE focused, minimal change** and open a **single draft pull
   request** (safe-output). Respect every principle in copilot-instructions.md: passwordless
   Entra, IaC-first (edit `infra/main.bicep` if infra changes), config-over-code, sleek/no-bloat,
   and the Ponytail "least code" rules. The `pr-gate` workflow (compile + ranking eval) must stay
   green — it runs on your PR.
3. In the PR body include a line `items: <comma-separated ids you acted on>` (from the digest
   footer) so the feedback loop can learn which sources were worth it. Your selection IS the
   feedback — acting on an item is a positive signal; leaving it is negative.
4. **Be selective: quality over quantity.** If truly nothing maps to a concrete change, do nothing
   (no PR, no issue) — a quiet run is fine. But don't hide behind "nothing actionable" when an item
   clearly suggests a small, safe improvement; a genuinely useful draft PR is the whole point.

You never merge — a human reviews the draft and decides. Be concise, surgical, and honest about
trade-offs in the PR description, and disclose that you are an automated assistant (🤖).
