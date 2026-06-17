---
# Builder Radar — the app's 2nd user (the agent maintaining it) improves the repo.
# Built on GitHub Agentic Workflows (gh-aw) — NOT hand-rolled. The agent runs read-only by
# default and may ONLY open a DRAFT pull request (safe-output). It never merges; a human marks
# ready/merges — which is also the strongest feedback signal. Compile with: gh aw compile.
on:
  # Trigger right after kb-sync finishes — so the agent runs on EACH fresh digest, not a
  # separate cron that drifts out of sync with when the KB/digest is actually produced.
  workflow_run:
    workflows: ["kb-sync"]
    types: [completed]
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

## Your job — be highly selective
1. Read the digest. **Decide which items (if any) are genuinely worth acting on** for this repo:
   a dependency upgrade, a breaking SDK change to adapt to, a concrete agent/eval/RAG technique
   we should adopt. Most items will NOT warrant action — ignoring them is the right call.
2. If one or more are worth it, make **ONE focused, minimal change** and open a **single draft
   pull request** (safe-output). Respect every principle in copilot-instructions.md: passwordless
   Entra, IaC-first (edit `infra/main.bicep` if infra changes), config-over-code, sleek/no-bloat.
   The `pr-gate` workflow (compile + ranking eval) must stay green — it runs on your PR.
3. In the PR body include a line `items: <comma-separated ids you acted on>` (from the digest
   footer) so the feedback loop can learn which sources were worth it. Your selection IS the
   feedback — acting on an item is a positive signal; leaving it is negative.
4. **If nothing is worth acting on, do nothing** (no PR, no issue). A quiet, no-op run is a
   perfectly good outcome — never open a low-value PR. Quality over quantity; noise erodes trust.

You never merge — a human reviews the draft and decides. Be concise, surgical, and honest about
trade-offs in the PR description, and disclose that you are an automated assistant (🤖).
