# Phase 0 Review: Open Items

Review date: 2026-06-18  
Last rechecked: 2026-06-19  
Reviewer stance: principal engineer, production readiness and abuse-resistance focus.

## Current Verdict

Phase 0 is now in a solid state for a small public production baseline. The earlier blocking
findings have been addressed in code and tests:

- SSRF DNS rebinding / TOCTOU risk: addressed by resolving and validating each hop, then pinning
  the outbound connection to the exact validated IP.
- Non-global IP handling: addressed by requiring globally routable IPs and rejecting CGNAT,
  private, loopback, link-local, reserved, multicast, unspecified, IPv6 ULA, and mapped private
  addresses.
- Subscribe rate-limit header trust: improved by preferring platform-observed socket IP, using the
  last forwarded hop when needed, and adding a global confirmation-send cap as a spoof-resistant
  backstop.
- Function route coverage: addressed with route-level tests for subscribe, confirm, unsubscribe,
  and feedback expiry.
- Rate-limit observability: addressed through structured App Insights log messages.
- ACS unsubscribe headers: accepted as addressed based on live E2E evidence that a welcome send
  with `List-Unsubscribe` succeeded.

No remaining P0/P1 blockers were found in this pass. The 2026-06-19 re-check found no new
blockers and no additional P2 closures; the open list below remains current.

## Verification Performed

- `.\.venv\Scripts\python.exe -m unittest discover -s tests -v`
  - Result: **121 tests passed**.
- Python compile check over package, builder, and Function:
  - Result: **45 files compiled**.
- `az bicep build --file infra\main.bicep`
  - Result: **passed**.
  - Warning: `BCP081` for `Microsoft.CognitiveServices/accounts/projects@2026-05-01`; non-blocking,
    but Bicep cannot validate that resource shape locally.

Rechecked on 2026-06-19 with the same commands:

- Unit tests: **121 tests passed**.
- Python compile check: **45 files compiled**.
- Bicep build: **passed** with the same non-blocking `BCP081` warning.

## Remaining Open Items

### P2: Welcome-edition feedback is generic

The instant welcome edition is cached generically and appears to carry generic feedback context.
That is acceptable for launch, but feedback from a new subscriber's welcome email may not
personalize that subscriber unless the welcome edition is re-rendered or tokens are reminted for
their profile at confirmation time.

Recommended decision:

- Keep it as global editorial signal for now and document that behavior, or
- Re-render/remint the welcome edition for the confirming user's profile before `_send_welcome()`.

**Addressed 2026-06-19:** the welcome edition now renders without feedback buttons (they were inert
for a new subscriber with no history, and the welcome lens is never reconciled). The first daily
edition carries working per-profile feedback; the welcome keeps its per-user unsubscribe link. See
`Orchestrator._cache_welcome_edition` and `docs/runbook.md`.

### P2: Static web API endpoint remains hardcoded

Files:

- `web/main.js`
- `web/staticwebapp.config.json`

The subscribe API origin is still hardcoded to the production Function host. This works for the
current deployment, but it makes staging, preview environments, and future host renames awkward.

Recommended action:

- Generate a `config.js` or `config.json` during deployment, or
- Use Static Web App app settings/build-time replacement.

**Addressed 2026-06-19:** the API origin moved to `web/config.js` (`window.APP_CONFIG.apiBase`);
`web/main.js` reads it. Swap that one file per environment — no code edit.

### P2: Alert enablement needs operator documentation

`alertEmail` defaults to empty, so alert resources do not deploy unless an operator opts in. That
is good for cost control, but production operations need an explicit checklist.

Recommended action:

- Document how to enable alerts.
- Add a deployment checklist item: set `alertEmail` in production.
- Include expected monthly cost and which rules are created.

**Addressed 2026-06-19:** documented in `docs/runbook.md` ("Enable alerts") — the `alertEmail`
opt-in, the three rules created, thresholds, and the ~$0.50/rule/mo cost.

### P2: Restore command needs a runbook

`ai_scout.cli.restore` exists and is tested, but there is no operator runbook yet.

Recommended action:

- Document how to list snapshots.
- Document how to restore the latest snapshot.
- Document how to restore a specific snapshot.
- Document the validation step after restore.
- Explicitly warn not to re-upload a restored KB until local validation passes.

**Addressed 2026-06-19:** documented in `docs/runbook.md` ("Restore the knowledge base") — list,
restore-latest, restore-specific, post-restore validation, and the do-not-re-upload-until-validated
warning.

## Acceptance Recommendation

Accept Phase 0 as meeting the intended production-hardening baseline, with the P2 items above
tracked as non-blocking operational/product follow-ups.

