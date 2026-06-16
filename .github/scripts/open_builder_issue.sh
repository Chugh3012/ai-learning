#!/usr/bin/env bash
# P12: open a weekly "builder radar" issue from the generated digest and hand it to the
# GitHub Copilot coding agent. Safe + idempotent-ish: if there's nothing new this week,
# it exits without opening an issue. If Copilot can't be assigned (not enabled), it labels
# the issue 'self-improve' instead so a human can pick it up. Never auto-merges anything.
set -euo pipefail

DIGEST="$(ls -t digests/builder-*.md 2>/dev/null | head -n1 || true)"
if [ -z "${DIGEST:-}" ] || [ ! -s "$DIGEST" ]; then
  echo "self-improve: no builder digest this week — nothing to do."
  exit 0
fi

# A digest with only the header (no items) means the queue was empty; skip.
if [ "$(grep -c '^- \|^### \|^| ' "$DIGEST" || true)" = "0" ] && [ "$(wc -l < "$DIGEST")" -lt 8 ]; then
  echo "self-improve: builder digest has no new items — skipping."
  exit 0
fi

# Dedup: don't open a new builder issue while a previous one is still open (avoid spam +
# don't pile work on the Copilot agent). A run only proceeds once the prior issue is closed.
OPEN_BUILDER="$(gh issue list --repo "$REPO" --state open --search 'in:title 🤖 Builder radar' --json number --jq 'length' 2>/dev/null || echo 0)"
if [ "${OPEN_BUILDER:-0}" != "0" ]; then
  echo "self-improve: a builder radar issue is still open — skipping until it's closed."
  exit 0
fi

TODAY="$(date -u +%Y-%m-%d)"
TITLE="🤖 Builder radar — ${TODAY}"

BODY_FILE="$(mktemp)"
{
  cat <<'EOF'
**You are the maintainer of this repo (ai-scout), acting as its 2nd user.**

Below is this week's *builder radar*: SDK/library/agent/eval news ranked for engineering
relevance to THIS codebase, reordered by past builder feedback. Treat it as a worklist.

**What to do**
1. Read each item. For anything genuinely useful to this pipeline (a dependency upgrade, a
   breaking SDK change to adapt to, an agent/eval/RAG technique we should adopt), make the
   change in a focused PR.
2. Ignore consumer/news items and anything not actionable for this repo.
3. Keep the project's principles: passwordless Entra, IaC-first (update infra/ Bicep if infra
   changes), sleek/no-bloat, config-over-code, and the CI eval-gate must stay green.
4. If an item isn't worth acting on, that's fine — no change is a valid outcome. The commit
   history is the record; nothing here needs to be remembered next week.

**Guardrails:** open a PR for review — do NOT merge to main. The eval-gate workflow will run
on PRs that touch ranking. One PR per coherent change is better than one giant PR.

---

EOF
  cat "$DIGEST"
} > "$BODY_FILE"

ISSUE_URL="$(gh issue create --repo "$REPO" --title "$TITLE" --body-file "$BODY_FILE")"
echo "self-improve: opened $ISSUE_URL"
ISSUE_NUM="${ISSUE_URL##*/}"

# --- Assign the Copilot coding agent via GraphQL (suggestedActors -> replaceActorsForAssignable) ---
# --- Assign the Copilot coding agent (best-effort). IMPORTANT: assignment requires a USER
# token (PAT/OAuth). The default Actions GITHUB_TOKEN is a GitHub App installation token and
# CANNOT assign agents (FORBIDDEN). So: if COPILOT_ASSIGN_TOKEN (a user PAT secret) is set we
# use it to auto-assign; otherwise we label the issue and leave a one-click instruction for a
# human. Either way the issue is created — the loop never fails the workflow. ---
OWNER="${REPO%/*}"; NAME="${REPO#*/}"
ASSIGN_TOKEN="${COPILOT_ASSIGN_TOKEN:-}"

label_for_human() {
  echo "self-improve: leaving #$ISSUE_NUM for a human to start Copilot (assign @Copilot or comment '@copilot start')."
  gh label create "self-improve" --repo "$REPO" --color FBCA04 --description "Agent self-improvement task" 2>/dev/null || true
  gh issue edit "$ISSUE_NUM" --repo "$REPO" --add-label "self-improve" 2>/dev/null || true
  gh issue comment "$ISSUE_NUM" --repo "$REPO" --body "Assign **Copilot** to this issue (or comment \`@copilot start\`) to begin. Auto-assign needs a user token; the Actions token can't assign agents." 2>/dev/null || true
}

if [ -z "$ASSIGN_TOKEN" ]; then
  echo "self-improve: no COPILOT_ASSIGN_TOKEN (user PAT) — can't auto-assign with the Actions token."
  label_for_human
  exit 0
fi

COPILOT_ID="$(GH_TOKEN="$ASSIGN_TOKEN" gh api graphql -f owner="$OWNER" -f name="$NAME" -f query='
  query($owner:String!, $name:String!) {
    repository(owner:$owner, name:$name) {
      suggestedActors(capabilities:[CAN_BE_ASSIGNED], first:100) {
        nodes { login __typename ... on Bot { id } ... on User { id } }
      }
    }
  }' --jq '.data.repository.suggestedActors.nodes[] | select(.login=="copilot-swe-agent") | .id' 2>/dev/null || true)"

if [ -z "${COPILOT_ID:-}" ]; then
  echo "self-improve: Copilot coding agent not assignable on this repo."
  label_for_human
  exit 0
fi

ISSUE_ID="$(gh api graphql -f owner="$OWNER" -f name="$NAME" -F num="$ISSUE_NUM" -f query='
  query($owner:String!, $name:String!, $num:Int!) {
    repository(owner:$owner, name:$name) { issue(number:$num) { id } }
  }' --jq '.data.repository.issue.id')"

if GH_TOKEN="$ASSIGN_TOKEN" gh api graphql -f assignableId="$ISSUE_ID" -f actorId="$COPILOT_ID" -f query='
  mutation($assignableId:ID!, $actorId:ID!) {
    replaceActorsForAssignable(input:{assignableId:$assignableId, actorIds:[$actorId]}) {
      assignable { ... on Issue { number assignees(first:5){nodes{login}} } }
    }
  }'; then
  echo "self-improve: assigned Copilot coding agent to #$ISSUE_NUM"
else
  echo "self-improve: auto-assign failed — falling back to human pickup."
  label_for_human
fi
