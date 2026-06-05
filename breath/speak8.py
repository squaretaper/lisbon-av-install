#!/usr/bin/env python3
"""
speak8.py — render a line with macOS `say`, optionally mangle it, and play it to
a specific ES-9 output channel (default ch16 = physical out 8). Run with breath/.venv python.

Usage: speak8.py "text" [voice]
  - If text starts with "GARBLE " it is bit-crushed + ring-modded (uncanny/garbled).
  - Volume / rate / pitch come from [[volm]] [[rate]] [[pbas]] embedded in the text.
Env: VOICE_DEV (ES-9), VOICE_CH (16), VOICE_NAME (Daniel)
Non-blocking lock: drops the utterance if the channel is already speaking (stays live).
"""
import sys, os, subprocess, fcntl, tempfile
import soundfile as sf, sounddevice as sd, numpy as np

text = sys.argv[1] if len(sys.argv) > 1 else ""
voice = sys.argv[2] if len(sys.argv) > 2 else os.environ.get("VOICE_NAME", "Daniel")
dev = os.environ.get("VOICE_DEV", "ES-9")
ch = int(os.environ.get("VOICE_CH", "16"))

garble = False
if text.startswith("GARBLE "):
    garble = True
    text = text[len("GARBLE "):]
if not text.strip():
    sys.exit(0)

lock = open("/tmp/speak8.lock", "w")
try:
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
except OSError:
    sys.exit(0)
try:
    tmp = tempfile.NamedTemporaryFile(suffix=".aiff", delete=False); tmp.close()
    subprocess.run(["say", "-v", voice, "-o", tmp.name, text], check=False,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    data, sr = sf.read(tmp.name, dtype="float32")
    if data.ndim > 1:
        data = data.mean(axis=1)
    if garble:
        q = 2 ** 5                                   # bit-crush
        data = np.round(data * q) / q
        t = np.arange(len(data)) / sr                # ring modulation (alien/garbled)
        data = (data * (0.55 + 0.45 * np.sin(2 * np.pi * 72 * t))).astype("float32")
        if data.size:                                # random brief dropouts
            n = max(1, len(data) // 4000)
            for _ in range(n):
                i = np.random.randint(0, max(1, len(data) - 300))
                data[i:i + np.random.randint(40, 220)] = 0.0
    sd.play(data, sr, device=dev, mapping=[ch]); sd.wait()
    try: os.unlink(tmp.name)
    except Exception: pass
except Exception:
    pass
finally:
    fcntl.flock(lock, fcntl.LOCK_UN)
