from __future__ import annotations

import contextlib
import wave
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol, runtime_checkable

# A timed word: (text, start_seconds, duration_seconds).
Word = tuple[str, float, float]

@dataclass
class Speech:
    audio_path: Path
    words: list[Word] = field(default_factory=list)
    duration: float = 0.0

@runtime_checkable
class TTS(Protocol):
    """A voiceover provider: synthesize text to an audio file and return per-word timings."""

    def synth(self, text: str, out_path: Path) -> Speech: ...

def wav_duration(path: str | Path) -> float:
    with contextlib.closing(wave.open(str(path), "rb")) as w:
        return w.getnframes() / float(w.getframerate() or 1)

def chunk_word_timings(words: list[Word], per_chunk: int) -> list[tuple[str, float, float]]:
    """Group timed words into caption chunks of `per_chunk`, each timed from its first word's start
    to its last word's end. This is what syncs the flashing captions to the spoken voice."""
    out: list[tuple[str, float, float]] = []
    for i in range(0, len(words), max(per_chunk, 1)):
        group = words[i:i + max(per_chunk, 1)]
        if not group:
            continue
        text = " ".join(w[0] for w in group)
        start = group[0][1]
        end = group[-1][1] + group[-1][2]
        out.append((text, start, max(end - start, 0.1)))
    return out
