# Operations Runbook

Concise operator reference for deploying and recovering ai-scout. Pairs with
`docs/long-term-vision-and-production.md` (strategy) — this file is the "how to run it" sheet.

All commands are passwordless (Entra / `az login` locally, OIDC in CI). No keys or secrets.

## Deploy

Source of truth is `infra/main.bicep`. Resources converge with RBAC skipped (default), so the
template re-deploys idempotently without colliding on pre-existing role assignments.

```pwsh
# infrastructure (RBAC skipped; add -p assignRoles=true only for a fresh environment)
az deployment group create -g rg-ai-scout -f infra/main.bicep

# function code (Flex remote build)
cd function; func azure functionapp publish fn-ai-scout-fb --python; cd ..

# website
$tok = az staticwebapp secrets list -g rg-ai-scout -n swa-ai-scout --query properties.apiKey -o tsv
npx @azure/static-web-apps-cli deploy ./web --deployment-token $tok --env production
```

Post-deploy smoke check (confirms the Function reads Tables via managed identity):

```pwsh
curl.exe -s -o NUL -w "%{http_code}" "https://fn-ai-scout-fb.azurewebsites.net/api/f?t=bogus"  # expect 404
```

The website API origin lives in `web/config.js` (`window.APP_CONFIG.apiBase`) — change that one
file for a staging/preview host or custom domain; no code edit needed.

## Source quality dashboard

Every `ai_scout.cli.sync` run refreshes `source-quality.md` — uploaded to the KB Blob container
when storage is configured, else written to `.scratch/source-quality.md` for local runs. Use it to
spot sources with low quality-ranked rate, weak engagement, or high skips before pruning
`config/sources.opml`.

## Preference center

Edition footers include `/api/preferences?t=<token>&p=<profile_id>`. The Function validates the
subscriber token, updates that user's `profiles` row, and the next pipeline run reads the new
`cadence`, `top`, `min_score`, and `interest` values automatically.

## Saved library

Edition footers include `/api/saved?t=<token>&p=<profile_id>`. Save clicks write item title and URL
into `feedbackevents`; the saved-library page reads only events for that token's profile lens.

## Enable alerts

Alert rules are opt-in so the default template costs `$0`. To turn them on, pass an operator email:

```pwsh
az deployment group create -g rg-ai-scout -f infra/main.bicep -p alertEmail="ops@example.com"
```

This deploys an action group plus three log-search rules over `AiScoutMetrics_CL`:

| Rule | Fires when | Severity |
|---|---|---|
| `ai-scout-no-sync-36h` | no `ingested` metric in 36h (pipeline stuck) | 1 |
| `ai-scout-feeds-failed` | `feeds_failed` in a day exceeds `alertFeedsFailedMax` (default 8) | 2 |
| `ai-scout-cost-budget` | daily `cost_usd` exceeds `alertCostBudgetUsd` (default 1) | 2 |

Cost: roughly $0.50 per rule per month (3 rules). Tune thresholds with the `alertFeedsFailedMax`
and `alertCostBudgetUsd` parameters. **Production checklist: set `alertEmail`.**

## Restore the knowledge base

The pipeline snapshots `kb.sqlite` on every upload (blob versioning + 14-day soft delete back it
up). Restore with the `ai_scout.cli.restore` command. Set the account first:

```pwsh
$env:STORAGE_ACCOUNT = "staiscoutv9uothke"; $env:BLOB_CONTAINER = "knowledge"

python -m ai_scout.cli.restore --list              # list available snapshots
python -m ai_scout.cli.restore                      # restore the latest snapshot
python -m ai_scout.cli.restore 2026-06-17T23:19:35.4Z   # restore a specific snapshot
```

Validate the restored KB **before** trusting it:

```pwsh
python -c "from ai_scout.repositories.knowledge import KnowledgeBase; kb=KnowledgeBase.open('data/kb/kb.sqlite'); print(kb.metrics_snapshot()); kb.close()"
```

Do **not** re-upload a restored KB until local validation passes — run with `--no-upload` while
verifying:

```pwsh
python -m ai_scout.cli.sync --no-upload
```

The `subscribers` / `profiles` tables live in the Function storage account and are untouched by a
KB restore, so an unsubscribed user stays unsubscribed across a restore.

## Note: welcome email feedback

The instant welcome edition is cached generically and sent without feedback buttons by design — a
brand-new subscriber has no history to personalize, and the welcome lens is never reconciled into
affinity. The subscriber's first daily edition carries working per-profile feedback. The welcome
still includes a per-user one-click unsubscribe link.
