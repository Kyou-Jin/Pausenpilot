"""Dezente, synthetisch erzeugte Töne (keine Audiodateien nötig).

Wiedergabe über winsound (Standardbibliothek) – asynchron aus WAV-Dateien im Temp-Ordner.
"""
from __future__ import annotations

import math
import random
import struct
import sys
import tempfile
import wave
from pathlib import Path

RATE = 44100
_cache: dict[tuple[str, int], Path] = {}


def _env(i: int, n: int, attack: int, decay_tau: float) -> float:
    a = min(1.0, i / max(1, attack))
    return a * math.exp(-i / (decay_tau * RATE))


def _click(vol: float) -> list[float]:
    """Weicher 'Klick' – wie ein leiser mechanischer Schalter."""
    n = int(RATE * 0.06)
    rnd = random.Random(7)
    out, lp = [], 0.0
    for i in range(n):
        t = i / RATE
        noise = rnd.uniform(-1, 1)
        lp += 0.35 * (noise - lp)                     # Tiefpass für weiches Rauschen
        body = math.sin(2 * math.pi * 1650 * t) * 0.55 + math.sin(2 * math.pi * 2900 * t) * 0.2
        s = (lp * 0.45 + body) * _env(i, n, 40, 0.006)
        out.append(s * vol)
    return out


def _tone(freq: float, dur: float, vol: float, tau: float = 0.09, harm: float = 0.18) -> list[float]:
    n = int(RATE * dur)
    out = []
    for i in range(n):
        t = i / RATE
        s = math.sin(2 * math.pi * freq * t) + harm * math.sin(2 * math.pi * freq * 2 * t)
        tail = 1.0 if i < n - 400 else max(0.0, (n - i) / 400)
        out.append(s * _env(i, n, 220, tau) * tail * vol / (1 + harm))
    return out


def _chime(vol: float) -> list[float]:
    """Sanfter Abschluss-Akkord (zwei Töne leicht versetzt)."""
    a = _tone(784.0, 1.1, vol * 0.8, tau=0.35)
    b = _tone(1174.7, 1.0, vol * 0.6, tau=0.3)
    off = int(RATE * 0.09)
    out = a[:] + [0.0] * off
    for i, s in enumerate(b):
        out[i + off] += s
    return out


def _write(path: Path, samples: list[float]) -> None:
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(RATE)
        frames = b"".join(struct.pack("<h", int(max(-1.0, min(1.0, s)) * 32000)) for s in samples)
        w.writeframes(frames)


_GENERATORS = {
    "click": lambda v: _click(v * 0.55),
    "tick": lambda v: _tone(880.0, 0.16, v * 0.30, tau=0.05),
    "chime": lambda v: _chime(v * 0.38),
}


def sound_file(name: str, volume: int) -> Path:
    volume = max(0, min(100, int(volume)))
    key = (name, volume)
    if key in _cache and _cache[key].exists():
        return _cache[key]
    d = Path(tempfile.gettempdir()) / "pausenpilot_sounds"
    d.mkdir(parents=True, exist_ok=True)
    p = d / f"{name}_{volume}.wav"
    if not p.exists():
        _write(p, _GENERATORS[name](volume / 100.0))
    _cache[key] = p
    return p


def play(name: str, volume: int = 60) -> None:
    if sys.platform != "win32" or volume <= 0:
        return
    try:
        import winsound
        winsound.PlaySound(str(sound_file(name, volume)),
                           winsound.SND_FILENAME | winsound.SND_ASYNC | winsound.SND_NODEFAULT)
    except Exception:
        pass
