"""Generate the bundled music bed for reelforge reels: a light DRIVING electronic loop (a punchy
kick, a sidechained bass, a soft minor-pentatonic arp, and quiet hats) at ~108 BPM. Synthesized from
scratch so it is licence-free (CC0) and reproducible. Run:
    python reelforge/assets/music/generate_ambient.py
Writes ambient.mp3 next to this file via the bundled ffmpeg. ponytail: a simple synthesized bed for
momentum; swap in any track by setting `music` in config/reel.json if you want something richer."""
from __future__ import annotations

import subprocess
import wave
from pathlib import Path

import imageio_ffmpeg
import numpy as np

SR = 44100
DUR = 60.0
HERE = Path(__file__).resolve().parent

BPM = 108.0
BEAT = 60.0 / BPM

def _hit(t, period, decay):
    # An exponential-decay envelope that re-triggers every `period` seconds.
    return np.exp(-(t % period) / decay)

def _kick(t):
    p = t % BEAT
    pitch = 110.0 * np.exp(-p / 0.03) + 45.0          # fast pitch drop -> punchy thump
    return np.sin(2 * np.pi * pitch * p) * np.exp(-p / 0.16)

def main() -> None:
    t = np.linspace(0, DUR, int(SR * DUR), endpoint=False)
    bar = 4 * BEAT
    step = BEAT / 2                                   # 8th notes
    duck = 0.35 + 0.65 * (1 - np.exp(-(t % BEAT) / 0.12))   # sidechain pump off the kick

    # Bassline: one root per bar, Am - F - C - G.
    bass = np.zeros_like(t)
    for i, f in enumerate((55.00, 43.65, 65.41, 49.00)):
        m = ((t % (4 * bar)) >= i * bar) & ((t % (4 * bar)) < (i + 1) * bar)
        bass += m * (np.sin(2 * np.pi * f * t) + 0.3 * np.sin(2 * np.pi * 2 * f * t))
    bass *= 0.55 * duck

    # Arp: A-minor pentatonic, 8th notes, soft triangle.
    scale = [220.0, 261.63, 293.66, 329.63, 392.00, 523.25]
    notes = np.array([scale[i % len(scale)] for i in range(int(DUR / step) + 2)])
    freq = notes[(t // step).astype(int)]
    tri = 1 - 2 * np.abs(2 * (t * freq % 1) - 1)
    arp = 0.16 * tri * _hit(t, step, 0.10) * duck

    # Hats: high-passed noise burst on each 8th, quiet.
    noise = np.random.default_rng(7).standard_normal(t.shape)
    hat = 0.05 * (noise - np.roll(noise, 1)) * _hit(t, step, 0.03) * duck

    mix = 0.9 * _kick(t) + bass + arp + hat
    # 1.5s fade in/out
    fade = np.ones_like(mix)
    n = int(SR * 1.5)
    fade[:n] = np.linspace(0, 1, n)
    fade[-n:] = np.linspace(1, 0, n)
    mix *= fade
    mix /= np.max(np.abs(mix))
    mix *= 0.7                                        # headroom; it gets ducked under the voice
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
