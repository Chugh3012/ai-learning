from __future__ import annotations

import json

from prism.lib import foundry
from prism.lib.text import clean

# Built-in FALLBACK brief (used when the playbook has no `visual_system`). The reel's WORDS are
# written elsewhere (ReelScripter); this layer decides what the viewer SEES and turns each beat into
# a vivid, filmable shot. The model returns a shared STYLE (a 'world bible') plus one SHOT per beat;
# _finish() weaves the style into every shot so the separate clips look like one film. HARD safety
# rails: Sora 2 rejects faces / real people / logos / on-screen text, so asking for them just fails.
_SYSTEM = (
    "You are the VISUAL DIRECTOR for a fast, entertaining VERTICAL (9:16) short video that explains "
    "ONE AI/tech story. You decide what the viewer SEES. You get the STORY and its ordered SPOKEN "
    "BEATS, and you return a shared visual STYLE plus exactly one SHOT per beat for an AI video "
    "generator (text-to-video).\n"
    "THINK IN METAPHOR: map each beat's IDEA to one striking, concrete, filmable image — not a "
    "literal diagram. 'An AI learns' -> a dark lattice of light rewiring itself as new threads "
    "ignite. Make it surprising enough that a thumb stops scrolling.\n"
    "STYLE = one shared world so the clips feel like a single film: pick a bold palette, a "
    "near-future tech aesthetic, ONE recurring motif, and a lighting signature. Keep the STYLE "
    "itself SHORT — an 8-15 word tag (palette + motif + lighting), never a paragraph, since it is "
    "repeated inside every shot.\n"
    "EACH SHOT is ONE continuous take with REAL MOTION (slow push-in, drifting orbit, rising crane, "
    "streaming particles, a turning machine). Use: subject + action + environment + camera move + "
    "lighting + mood. Keep it SINGLE-PURPOSE — one subject, one action — so the model nails it. "
    "Describe ONLY what is visibly on screen — never meaning/intent words ('symbolizing', 'evoking', "
    "'representing', 'reflecting', 'to convey'); show the idea, don't explain it. One or two crisp "
    "sentences.\n"
    "COMPOSE FOR VERTICAL: keep the focal subject in the UPPER TWO-THIRDS and the lower third "
    "calmer and less busy, because captions overlay there.\n"
    "HARD RULES (the generator REJECTS these — NEVER include them): no real people or public "
    "figures, no recognizable human faces, no brand names / logos / real products, no on-screen "
    "text / words / numbers / UI copy, no copyrighted characters. If a person is unavoidable, use a "
    "distant faceless silhouette. Show AI and technology ABSTRACTLY and symbolically: glowing "
    "neural lattices, rivers of data, vast server halls, robotic arms, holographic volumes, "
    "drifting light particles, circuit-board landscapes, luminous geometry, sleek unbranded "
    "devices.\n"
    "Return ONLY JSON: {\"style\":\"<shared palette + aesthetic + motif + lighting, one sentence>\","
    " \"shots\":[\"<beat 1 shot>\", \"<beat 2 shot>\", ...]} with EXACTLY one shot per beat, in order."
)

# Appended to every woven prompt so the look stays cohesive and inside the generator's safe envelope.
_SUFFIX = (", cinematic, dynamic camera motion, vertical 9:16 composition, volumetric lighting, "
           "ultra-detailed, no text, no logos, no readable words, no watermark")

class VisualPromptWriter:
    """Turns a reel's spoken beats into rich, cohesive, safety-constrained visual prompts for an AI
    video provider — one batched LLM call per reel (cheap). The model returns a shared STYLE plus one
    shot per beat; each shot is woven with that style so the separate generations share one world.
    Graceful: returns empty strings when unconfigured or on failure, so each scene falls back to its
    own keyword `query` and nothing breaks. This is the creative layer that makes generated visuals
    look directed, not generic."""

    def __init__(self, endpoint: str, model: str):
        self.endpoint = endpoint
        self.model = model

    def write(self, title: str, body: str, beats: list[str], system: str = "") -> list[str]:
        # `system` = the playbook's visual brief (config); empty falls back to the built-in default.
        if not beats:
            return []
        if not self.endpoint:
            return ["" for _ in beats]
        try:
            client = foundry.openai_client(self.endpoint)
        except Exception as e:
            print(f"reel: visual-prompt client failed ({e}); using keyword b-roll")
            return ["" for _ in beats]
        listing = "\n".join(f"[{i}] {b}" for i, b in enumerate(beats))
        user = f"STORY: {title}\n\n{clean(body, 1500)}\n\nSPOKEN BEATS:\n{listing}"
        try:
            # Model-agnostic call: no `temperature` and `max_completion_tokens` so a reasoning model
            # (gpt-5.x) works as well as the mini fallback; the budget has headroom for the model's
            # hidden reasoning tokens so the JSON answer is never starved/truncated.
            resp = client.chat.completions.create(
                model=self.model,
                messages=[{"role": "system", "content": system or _SYSTEM},
                          {"role": "user", "content": user}],
                response_format={"type": "json_object"}, max_completion_tokens=4000)
            foundry.log_usage("reel-visual", resp, self.model)
            data = json.loads(resp.choices[0].message.content)
            style = str(data.get("style", ""))
            shots = [self._finish(str(s), style) for s in data.get("shots", [])]
        except Exception as e:
            print(f"reel: visual-prompt generation failed ({e}); using keyword b-roll")
            return ["" for _ in beats]
        # The model can miscount; pad/truncate to exactly one prompt per beat, preserving order.
        return (shots + ["" for _ in beats])[: len(beats)]

    @staticmethod
    def _finish(shot: str, style: str) -> str:
        # Weave the shared world into each shot (subject-first), then the format/safety suffix.
        shot = " ".join(shot.split()).strip().rstrip(".")
        if not shot:
            return ""
        style = " ".join(style.split()).strip().rstrip(".")
        return (f"{shot}. {style}" if style else shot) + _SUFFIX
