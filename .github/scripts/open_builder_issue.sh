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
OWNER="${REPO%/*}"; NAME="${REPO#*/}"

COPILOT_ID="$(gh api graphql -f owner="$OWNER" -f name="$NAME" -f query='
  query($owner:String!, $name:String!) {
    repository(owner:$owner, name:$name) {
      suggestedActors(capabilities:[CAN_BE_ASSIGNED], first:100) {
        nodes { login __typename ... on Bot { id } ... on User { id } }
      }
    }
  }' --jq '.data.repository.suggestedActors.nodes[] | select(.login=="copilot-swe-agent") | .id' 2>/dev/null || true)"

if [ -z "${COPILOT_ID:-}" ]; then
  echo "self-improve: Copilot coding agent not assignable on this repo — labeling for human pickup."
  gh issue edit "$ISSUE_NUM" --repo "$REPO" --add-label "self-improve" 2>/dev/null || \
    { gh label create "self-improve" --repo "$REPO" --color FBCA04 --description "Agent self-improvement task" 2>/dev/null && \
      gh issue edit "$ISSUE_NUM" --repo "$REPO" --add-label "self-improve"; }
  exit 0
fi

ISSUE_ID="$(gh api graphql -f owner="$OWNER" -f name="$NAME" -F num="$ISSUE_NUM" -f query='
  query($owner:String!, $name:String!, $num:Int!) {
    repository(owner:$owner, name:$name) { issue(number:$num) { id } }
  }' --jq '.data.repository.issue.id')"

gh api graphql -f assignableId="$ISSUE_ID" -f actorId="$COPILOT_ID" -f query='
  mutation($assignableId:ID!, $actorId:ID!) {
    replaceActorsForAssignable(input:{assignableId:$assignableId, actorIds:[$actorId]}) {
      assignable { ... on Issue { number assignees(first:5){nodes{login}} } }
    }
  }' && echo "self-improve: assigned Copilot coding agent to #$ISSUE_NUM"
