"""Generate the bundled ambient music bed for reelforge reels. Synthesized from scratch (sine pads
+ slow swell + a soft pulse), so it is licence-free (CC0) and reproducible. Run:
    python reelforge/assets/music/generate_ambient.py
Writes ambient.mp3 next to this file via the bundled ffmpeg. ponytail: a simple ambient bed under a
voiceover; swap in any track by setting `music` in config/reel.json if you want something richer."""
from __future__ import annotations

import subprocess
import wave
from pathlib import Path

import imageio_ffmpeg
import numpy as np

SR = 44100
DUR = 60.0
HERE = Path(__file__).resolve().parent

def _tone(freq, t, detune=0.0):
    return np.sin(2 * np.pi * freq * t) + 0.5 * np.sin(2 * np.pi * (freq * (1 + detune)) * t)

def main() -> None:
    t = np.linspace(0, DUR, int(SR * DUR), endpoint=False)
    # Am pad: A2 / E3 / A3 / C4, warm detuned sines.
    pad = sum(_tone(f, t, 0.002) for f in (110.0, 164.81, 220.0, 261.63))
    pad /= np.max(np.abs(pad))
    swell = 0.55 + 0.45 * np.sin(2 * np.pi * 0.05 * t)            # slow breathing
    shimmer = 0.06 * np.sin(2 * np.pi * 880.0 * t) * (0.5 + 0.5 * np.sin(2 * np.pi * 0.07 * t))
    pulse_env = 0.5 * (1 + np.cos(2 * np.pi * (t % 0.6) / 0.6)) ** 4   # gentle ~100bpm pulse
    sub = 0.12 * np.sin(2 * np.pi * 55.0 * t) * pulse_env
    mix = pad * swell * 0.6 + shimmer + sub
    # 2s fade in/out
    fade = np.ones_like(mix)
    n = int(SR * 2)
    fade[:n] = np.linspace(0, 1, n)
    fade[-n:] = np.linspace(1, 0, n)
    mix *= fade
    mix /= np.max(np.abs(mix))
    mix *= 0.5                                                    # leave headroom; it gets ducked
    pcm = (mix * 32767).astype("<i2")
    stereo = np.repeat(pcm[:, None], 2, axis=1).tobytes()

    wav = HERE / "ambient.wav"
    with wave.open(str(wav), "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(stereo)
    subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(), "-y", "-i", str(wav), "-b:a", "96k",
                    str(HERE / "ambient.mp3")], check=True, capture_output=True)
    wav.unlink()
    print("wrote", HERE / "ambient.mp3")

if __name__ == "__main__":
    main()
