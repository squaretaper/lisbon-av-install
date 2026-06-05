#!/usr/bin/env python3
"""
beat.py — a "Soul Train arrival": a rising approach-sweep into a funky 4-on-the-floor
kick + hat groove, synthesized with numpy and played to ES-9 (default ch16 = out 8).
Run with breath/.venv python.  Usage: beat.py [bars]   Env: VOICE_DEV, VOICE_CH
Uses the same non-blocking lock as the voice so it owns the channel for the drop.
"""
import sys, os, fcntl, numpy as np, sounddevice as sd

SR = 44100
dev = os.environ.get("VOICE_DEV", "ES-9")
ch = int(os.environ.get("VOICE_CH", "16"))
bars = int(sys.argv[1]) if len(sys.argv) > 1 else 6
bpm = 112.0
spb = int(SR * 60.0 / bpm)            # samples per beat

def kick(dur=0.28):
    t = np.linspace(0, dur, int(SR * dur), False)
    freq = 45 + 75 * np.exp(-t * 32)          # pitch drop 120->45
    return (np.sin(2 * np.pi * np.cumsum(freq) / SR) * np.exp(-t * 14)).astype("float32")
def hat(dur=0.05):
    t = np.linspace(0, dur, int(SR * dur), False)
    return (np.random.uniform(-1, 1, len(t)) * np.exp(-t * 90) * 0.28).astype("float32")
def sub(dur, f=55):
    t = np.linspace(0, dur, int(SR * dur), False)
    return (np.sin(2 * np.pi * f * t) * 0.18 * np.minimum(1, t * 4)).astype("float32")
def approach(dur=2.4):                          # the train pulling in: rising sweep
    t = np.linspace(0, dur, int(SR * dur), False)
    f = 220 + 1600 * (t / dur) ** 2
    env = np.minimum(1, t * 1.5) * (0.2 + 0.3 * (t / dur))
    horn = np.sin(2 * np.pi * np.cumsum(f) / SR) * env
    chug = np.sin(2 * np.pi * 8 * t) * 0.0 + (np.random.uniform(-1,1,len(t)) * np.exp(-(t%0.25)*30) * 0.08 * (t/dur))
    return (horn * 0.22 + chug).astype("float32")

def mix(into, clip, at):
    end = min(len(into), at + len(clip))
    into[at:end] += clip[:end - at]

total = int(spb * 4 * bars) + int(SR * 2.6)
buf = np.zeros(int(SR * 2.4) + total, dtype="float32")
mix(buf, approach(2.4), 0)                       # arrival sweep
start = int(SR * 2.4)
for b in range(bars * 4):                         # the groove
    at = start + b * spb
    mix(buf, kick(), at)                          # 4-on-the-floor kick
    mix(buf, hat(), at + spb // 2)                # offbeat hat
    if b % 4 == 2:
        mix(buf, hat(0.04), at + spb // 4)        # syncopation
for b in range(0, bars * 4, 4):
    mix(buf, sub(60.0 / bpm * 4 * 0.95), start + b * spb)   # bass under each bar

m = np.max(np.abs(buf)) or 1.0
buf = np.tanh(buf / m * 1.7).astype("float32")  # drive hot + soft-clip = LOUD

lock = open("/tmp/speak8.lock", "w")
try: fcntl.flock(lock, fcntl.LOCK_EX)             # take the channel for the drop
except OSError: pass
try:
    sd.play(buf, SR, device=dev, mapping=[ch]); sd.wait()
finally:
    fcntl.flock(lock, fcntl.LOCK_UN)
