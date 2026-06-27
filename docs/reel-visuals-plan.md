# Reel visuals — AI generation initiative

**Goal:** replace stock-heavy Pexels b-roll (gets filtered/downranked on Instagram) with
AI-generated 9:16 clips, so reels feel scroll-native. Hybrid by default (AI hero beats + Pexels
fallback); full-AI 15s reels acceptable when they're genuinely entertaining.

**North-star constraints (don't break):**
- Passwordless / Entra-first. No stored API keys for the primary path.
- Infra-as-code (`infra/main.bicep`) is the source of truth for any Azure resource.
- Every stage optional + graceful: visuals no-op → fall back (Pexels → branded gradient), never crash.
- Eval-gate grades the ranker only → renderer changes are gate-safe.
- Cost-conscious: cap AI spend per run; pay-per-use; nothing always-on.

## Decision: primary provider = Azure Sora 2 (Foundry)
First-party video in Azure OpenAI — the only path that's passwordless, IaC, on the existing
`aiscoutageony` account, and billed to VS Enterprise credits. Native 9:16 (720x1280), text→video and
image→video (first-frame anchor), 4/8/12s (up to 20s), **$0.10/s** (5s=$0.50, 15s=$1.50).
RAI limits: no real people/public figures, input images with human faces rejected → abstract
AI/tech b-roll only. Status: **preview** (could change). Pexels stays as the always-on fallback.

## Architecture (where it plugs in)
- `prism/cli/reel.py` builds `reelforge.Storyboard` and calls `reelforge.render(sb, out, tts, visuals)`.
- Provider seam = `reelforge/providers/visuals/base.py` `Visual` protocol:
  `background(query, seconds, style, tmp) -> clip | None` (None → gradient) + `close()`.
- Today: `PexelsVisuals` only. New: `SoraVisuals` implementing the same protocol.
- Captions are timed off Azure Speech word boundaries → **keep Azure TTS** until a challenger proves
  word-level timestamps map to `chunk_word_timings`.

## Phases

### Phase 0 — Provider seam + dry run (free, no spend) ✅
- [x] `reelforge/providers/visuals/sora.py` `SoraVisuals(Visual)` — Azure Sora 2 job: create →
      poll → download mp4 → `cover_crop` → subclip to `seconds`. Graceful → None on any failure.
- [x] `dry_run` flag: log the prompt/payload, return None (review prompts with $0 spend).
- [x] `make_visuals(settings, creative, ai_visuals)` factory (`prism/services/reel_visuals.py`),
      default `pexels`, fallback ladder `FallbackVisuals([sora, pexels])` → gradient.
- [x] Settings `foundry_sora_deployment` + `config/reel.json` `visuals`/`sora` + `config/flags.json`
      `ai_visuals: false` + `.env.example` + `openai>=2.43` pin.
- [x] Offline tests (`tests/test_reel_visuals.py`): dry-run Sora → None, fallback ladder, factory pick.

### Phase 1 — Infra (passwordless, IaC)
- [x] Add `soraDeployment` to `infra/main.bicep`, chained after `embedDeployment`, gated `deploySora`
      (default off until model name/version/SKU confirmed). Bicep builds clean.
- [ ] Confirm reel workflow MI role/audience for video jobs on the Cognitive Services account.
- [ ] `az deployment group create -p deploySora=true` + verify the `sora` deployment exists. **(needs approval)**

### Phase 2 — Lab validation (a few dollars)
- [x] `.scratch/sora_lab.py` — reuses the real pipeline, forces AI visuals for one topic; **defaults
      to dry-run ($0)** printing every visual prompt, `--wet` to actually call Sora.
- [ ] Eyeball AI beat vs all-Pexels. **Go/no-go decision recorded below. (needs approval to spend)**

### Phase 3 — Prompt + quality (the real work)
- [x] Dedicated prompt layer `prism/services/reel_visual_prompt.py` `VisualPromptWriter`: one batched
      LLM call per reel returns a shared `style` (world-bible) + one shot per beat, woven so the
      separate clips look like one film; metaphor-driven, vertical-composed (focal subject upper
      two-thirds, caption-safe lower third), RAI-safe (no faces/people/logos/text). `reel.py` fills
      `Scene.visual_prompt` per beat when AI visuals are on. Graceful → keyword b-roll.
- [x] Prompt is EDITABLE CONFIG: `config/playbooks/explainer.json` `visual_system` (like `deep_system`),
      with a strong built-in fallback. Iterate via `.scratch/prompt_lab.py` ($0, one Foundry call).
- [ ] Optional: generate first frame (GPT-Image/Imagen) → image→video for tighter control.
- [ ] Tune to 15s entertaining (deep mode, ~2–3 beats × 5–8s) — needs live eyeballing.

### Phase 4 — Production wiring (guarded)
- [ ] Flip `config/flags.json` `ai_visuals` (or per-topic) — **deferred until lab go/no-go**.
- [x] Cost cap: `SoraVisuals.max_seconds` per render (config `sora.max_seconds`) → over budget = Pexels.
      `--ai-visuals`/`--dry-visuals` CLI overrides for the lab. `reel-render.yml` unchanged.
- [x] Keep Pexels fallback always on (fallback ladder).

### Phase 5 — TTS challengers (separate track, optional)
- [ ] Keep Azure Speech (word timings → captions). A/B Cartesia Sonic 3.5 / ElevenLabs in the lab on
      the same transcript; adopt only if timestamps map cleanly. Non-blocking.

## Cost ledger
| Format | Sora seconds | Est. cost | Notes |
| --- | --- | --- | --- |
| 1 test beat | 5s | $0.50 | Phase 2 |
| 15s full-AI reel | ~15s | ~$1.50 | 2–3 beats |
| Daily (2 reels) | ~30s | ~$3/day (~$90/mo) | needs cost cap + flag before daily |

## Decision log
- 2026-06-26 — Primary = Azure Sora 2 (passwordless/IaC/credits). Pexels stays as fallback. User OK
  with 15s full-AI reels if entertaining. Tracking doc created.
- 2026-06-26 — Phases 0/1/3/4 implemented (provider seam, gated infra, prompt layer, cost cap),
  225 offline tests green, bicep builds. Deploy + lab spend gated on approval (Phases 1–2 tails).
- 2026-06-26 — Prompt layer upgraded to best-in-class: shared `style` world-bible woven into every
  shot, metaphor-driven, vertical caption-safe composition; moved to editable playbook config
  (`visual_system`) + `.scratch/prompt_lab.py` to iterate at $0. 226 tests green.
- 2026-06-26 — Visual-prompt model upgraded mini → **gpt-5.4** (frontier reasoning) via a dedicated
  `visual` model task + `pro` deployment (ranker/scripter stay on mini). Deployed live + codified in
  bicep. Reasoning follows the constraints better (zero visible-only slips) and is bolder/cinematic.
  ~$0.03/reel ≈ ~$1/mo at one video/day. Writer call made model-agnostic (no temperature,
  `max_completion_tokens`). gpt-5.5 had no quota in eastus2; gpt-4.1/`-chat` variants deprecating.
