"""reelforge — an owned, reusable sub-library for generating short-form vertical videos
from a structured Storyboard. Pluggable providers (voiceover, b-roll, music, publish) layer on
top of a MoviePy compositor. Domain-agnostic: prism builds a Storyboard from ranked AI items and
calls render(); reelforge owns *how* to make it look like a reel."""
from __future__ import annotations

from reelforge.domain.storyboard import Scene, Storyboard
from reelforge.domain.style import Style
from reelforge.providers.tts.azure_speech import AzureSpeech
from reelforge.render.compositor import render

__all__ = ["Scene", "Storyboard", "Style", "AzureSpeech", "render"]
