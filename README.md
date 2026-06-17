# ai-scout

A passwordless, cost-efficient pipeline that scans AI/LLM sources, ranks them with a Foundry
model, personalizes per user, and delivers a daily top-N — with a feedback loop that tunes it.
**How it's built: [.github/copilot-instructions.md](.github/copilot-instructions.md).** What changed when: `git log`.

## Map
```
config/      what grows (sources.opml · users.json · tags.json · content.yml · *.json knobs)
ai_scout/    the ENGINE — layered package: domain/ (models) · repositories/ (KB · Blob · Feedback · registry) · services/ (rank · embed · curate · select · brief · deliver · ingest · discover · eval) · lib/ · cli/ (sync orchestrator · evaluate gate)
agent/       the builder as a USER — consumes its delivery: inbox (read digest) · review (vote keep/skip) · outcome (PR-merge 👍). Never touches the KB.
function/    passwordless Azure Function that captures feedback clicks
infra/       main.bicep — every Azure resource (source of truth)
tests/       offline unit tests for the deterministic core (run: python -m unittest discover -s tests)
.github/     pr-gate (compile + tests + ranking eval) · kb-sync cron · builder-radar (self-improve)
data/ digests/ drafts/   generated output (git-ignored)
```

## Run it
```sh
cp .env.example .env                              # fill in Azure resource names (no secrets)
python -m ai_scout.cli.sync --help                # all flags and what they do
python -m ai_scout.cli.sync --days 7 --no-upload  # local sync, no cloud writes
python -m ai_scout.cli.sync --rank --deliver      # score + deliver each user's top-N
```
Auth is passwordless (Entra): `az login` locally, GitHub OIDC in CI. No keys or secrets.

## Extend it
Growth is config, not code. Add a source, user, tag, or content profile by editing one config
file under `config/`. Adding an Azure resource means editing `infra/main.bicep`, never the Portal.
