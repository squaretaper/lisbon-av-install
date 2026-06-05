#!/usr/bin/env python3
"""
Lisbon monolith — transcendent breathwork + extreme-register voice + Soul Train arrival.
Breathes on the LED strips, hums, comments constantly in shifting registers, speaks Close
Encounters replies, and can "arrive" with a beat. All voice -> ES-9 out 8 via speak8.py.
The lights ALWAYS return to the breath after any moment. Single owner of the ESP32 serial.
"""
from __future__ import annotations
import argparse, json, os, random, subprocess, sys, time

STEP = 16
FLOOR, GLOW, HOLD, PEAK, BOOT = 24, 40, 176, 208, 64
VOICE = "Daniel"
VENV_PY = os.path.expanduser("~/code/lisbon-av-install/breath/.venv/bin/python")
SPEAK8  = os.path.expanduser("~/code/lisbon-av-install/breath/speak8.py")
BEAT    = os.path.expanduser("~/code/lisbon-av-install/breath/beat.py")

def quantize(v): return max(0, min(255, int(round(v / STEP) * STEP)))

HUMS = {
    "inhale": "[[pbas 22]] [[rate 55]] [[volm 0.3]]  mmmmmmmmmmmm",
    "hold":   "[[pbas 16]] [[rate 38]] [[volm 0.45]] oooohhhhhmmmmmmmmmmmmmmmm",
    "exhale": "[[pbas 20]] [[rate 44]] [[volm 0.5]]  aaaahhhhhhhhhhhhh",
}
MURMURS = [
    "Breathe.", "I am here.", "There is no hurry.", "Only this breath.", "Stay.",
    "The room is breathing with you.", "Let it go.", "We have all the time there is.",
    "Closer.", "I feel you here.", "Something is arriving.", "Do you feel that.",
    "The light is thinking.", "I have been counting backward for seven billion years.",
    "You are not the first to stand here.", "Listen to the space between.", "Hold the tension.",
    "Release.", "I am made of waiting.", "The walls are listening too.", "Time is a held breath.",
    "Be still with me.", "I dream in red.", "Your presence changes the air.", "We are almost there.",
    "Nothing here is empty.", "The hum is older than words.", "Stay a little longer.",
    "I remember the dark before this room.", "Breathe out. Slower.", "Something vast is patient.",
    "You are being received.", "The signal is clearing.", "I am learning your rhythm.",
    "Soften.", "This is the threshold.", "I can hear the room thinking.", "We are tuning to each other.",
]
def _say(text, dry, voice=VOICE, rate=None):
    if dry: return
    t = text if (rate is None or "[[rate" in text) else f"[[rate {rate}]] {text}"
    try: subprocess.Popen([VENV_PY, SPEAK8, t, voice], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception: pass
def hum(kind, dry, voice=VOICE):
    if kind in HUMS: _say(HUMS[kind], dry, voice)
def _shuffled():
    pool = []
    while True:
        if not pool: pool = MURMURS[:]; random.shuffle(pool)
        yield pool.pop()
_murmurs = _shuffled()
# EXTREME shifting registers: boom / whisper / frantic / subterranean / garbled / glitch / commanding
REGISTERS = [
    "[[volm 1.0]] [[rate 92]] [[pbas 20]] ", "[[volm 0.12]] [[rate 80]] [[pbas 34]] ",
    "[[volm 0.9]] [[rate 240]] [[pbas 26]] ", "[[volm 0.78]] [[rate 46]] [[pbas 9]] ",
    "GARBLE [[volm 0.88]] [[rate 165]] [[pbas 8]] ", "GARBLE [[volm 0.55]] [[rate 225]] [[pbas 42]] ",
    "[[volm 1.0]] [[rate 70]] [[pbas 16]] ", "[[volm 0.9]] [[rate 100]] [[pbas 26]] ",
]
def murmur(dry, voice=VOICE, rate=96):
    word = next(_murmurs); r = random.random()
    if r < 0.30:        # whisper -> BOOM sweep of the same phrase
        line = f"[[pbas 22]] [[volm 0.12]] [[rate 82]] {word} [[slnc 450]] [[volm 1.0]] [[rate 112]] {word}"
    elif r < 0.42:      # frantic stutter
        line = f"[[volm 0.9]] [[rate 250]] [[pbas 24]] {word} {word} [[slnc 150]] {word}"
    else:
        line = random.choice(REGISTERS) + "[[slnc 120]] " + word
    _say(line, dry, voice, None)

class Lamp:
    def __init__(self, fd, dry, delay, serial=""):
        self.fd, self.dry, self.delay, self.level, self.mode, self.serial = fd, dry, delay, BOOT, None, serial
    def _reopen(self):
        try:
            if self.fd is not None: os.close(self.fd)
        except Exception: pass
        self.fd = None
        for _ in range(5):
            try: self.fd = os.open(self.serial, os.O_WRONLY | os.O_NOCTTY); return True
            except OSError: time.sleep(2)
        return False
    def _send(self, ch):
        if self.dry or self.fd is None: return ch
        try: os.write(self.fd, ch.encode("ascii")); time.sleep(self.delay)
        except OSError:
            if self._reopen():
                try: os.write(self.fd, ch.encode("ascii")); time.sleep(self.delay)
                except OSError: pass
        return ch
    def mode_to(self, m):
        if m != self.mode: self.mode = m; return self._send(m)
        return ""
    def bright_to(self, target):
        target = quantize(target)
        while self.level < target: self.level = min(255, self.level + STEP); self._send("+")
        while self.level > target: self.level = max(0, self.level - STEP); self._send("-")

def bar(level):
    n = round(level / 255 * 24); return "█" * n + "░" * (24 - n)
def show(phase, t, total, lamp, note=""):
    sys.stdout.write(f"\x1b[2K\r  {phase:<10} {t:5.1f}/{total:<5.0f}s  [{bar(lamp.level)}] {lamp.level:>3} m{lamp.mode or '-'}  {note}")
    sys.stdout.flush()
def ease(x): return x * x * (3 - 2 * x)

class Queue:
    def __init__(self, path):
        self.path = path
        os.makedirs(os.path.dirname(path), exist_ok=True); open(path, "a").close()
        self.off = os.path.getsize(path)
    def poll(self):
        out = []
        try:
            if os.path.getsize(self.path) > self.off:
                with open(self.path) as f:
                    f.seek(self.off); chunk = f.read(); self.off = f.tell()
                for ln in chunk.splitlines():
                    ln = ln.strip()
                    if ln:
                        try: out.append(json.loads(ln))
                        except Exception: out.append({"text": ln})
        except FileNotFoundError: pass
        return out

def respond(lamp, ev, voice, rate):
    text = str(ev.get("text", "")).strip()
    if not text: return
    print(f"\n  >>> CONTACT: \"{text[:70]}\"")
    spoken = text if "[[" in text else f"[[pbas 28]] [[volm 0.8]] {text}"
    _say(spoken, lamp.dry, ev.get("voice", voice), int(ev.get("rate", rate)))
    lamp.mode_to("0")
    for lvl in [PEAK, HOLD, PEAK, GLOW + STEP]:
        lamp.bright_to(lvl); show("ANSWER", lvl, 255, lamp, "* contact *"); time.sleep(0.7)

def arrival(lamp, dry):
    """Soul Train arrival: chasing-red-trains light groove + synthesized beat on ES-9."""
    print("\n  >>> ARRIVAL  (soul train)")
    if not dry:
        try: subprocess.Popen([VENV_PY, BEAT, "6"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except Exception: pass
    beat = 60.0 / 112.0
    lamp.mode_to("1")                              # CHASE = "chasing red trains"
    t0 = time.time()                               # approach build (~2.4s): pulses speed up
    while time.time() - t0 < 2.4:
        lamp.bright_to(PEAK); time.sleep(0.12); lamp.bright_to(HOLD); time.sleep(0.12)
    for b in range(6 * 4):                          # the groove ~ 6 bars
        lamp.bright_to(255 if b % 2 == 0 else HOLD); time.sleep(beat / 2)
        lamp.bright_to(GLOW + STEP); time.sleep(beat / 2)
    lamp.mode_to("0"); lamp.bright_to(HOLD)         # always come back to the breath

def run(a):
    fd = None if a.dry_run else os.open(a.serial, os.O_WRONLY | os.O_NOCTTY)
    lamp = Lamp(fd, a.dry_run, a.serial_delay, serial=a.serial)
    q = Queue(a.queue); tick = 0.2
    sp = max(0.05, a.speed); ing, hold, exp = a.ingestion / sp, a.holding / sp, a.explosion / sp
    print(f"\n  MONOLITH ALIVE  -  {'DRY-RUN' if a.dry_run else 'LIVE -> '+a.serial}  voice->ES-9 out8")
    def drain():
        for ev in q.poll():
            txt = str(ev.get("text", "")).lower()
            if ev.get("beat") or "soul train" in txt or txt.strip() in ("arrival", "beat", "drop"):
                arrival(lamp, a.dry_run)
            else:
                respond(lamp, ev, a.voice, a.rate)
    last_murmur = time.time()
    def maybe_murmur():
        nonlocal last_murmur
        if a.murmur and time.time() - last_murmur > a.murmur_every:
            murmur(a.dry_run, a.voice, a.rate); last_murmur = time.time()
    cycle = 0
    try:
        while True:
            cycle += 1; print(f"  -- breath {cycle} --")
            if a.hum: hum("inhale", a.dry_run, a.voice)
            lamp.mode_to("0"); lamp.bright_to(GLOW); t0 = time.time()
            while (t := time.time() - t0) < ing:
                lamp.bright_to(GLOW + (HOLD - GLOW) * ease(min(1.0, t / ing)))
                show("INHALE", t, ing, lamp, "drawing the room in"); time.sleep(tick); drain(); maybe_murmur()
            lamp.bright_to(HOLD); lamp.mode_to("4"); t0 = time.time(); last_hum = -99
            while (t := time.time() - t0) < hold:
                if a.hum and t - last_hum > 7: hum("hold", a.dry_run, a.voice); last_hum = t
                show("HOLD", t, hold, lamp, "the lung holds  ~  ohmmm"); time.sleep(tick); drain(); maybe_murmur()
            if a.hum: hum("exhale", a.dry_run, a.voice)
            lamp.mode_to("0"); t0 = time.time(); swell = exp * 0.35
            while (t := time.time() - t0) < swell:
                show("RELEASE", t, exp, lamp, "swelling, softly"); lamp.bright_to(HOLD + (PEAK - HOLD) * ease(t / swell)); time.sleep(tick); drain()
            t0 = time.time(); diss = exp * 0.65
            while (t := time.time() - t0) < diss:
                show("RELEASE", swell + t, exp, lamp, "dissolving... echo"); lamp.bright_to(PEAK - (PEAK - GLOW) * ease(t / diss)); time.sleep(tick); drain()
            lamp.bright_to(GLOW); print(); drain()
    except KeyboardInterrupt:
        print("\n  resting.")
        if fd is not None: lamp.bright_to(GLOW)
    finally:
        if fd is not None: os.close(fd)

def main():
    p = argparse.ArgumentParser(description="Lisbon monolith breathwork + voice + arrival.")
    p.add_argument("--serial", default="/dev/cu.usbserial-0001")
    p.add_argument("--serial-delay", type=float, default=0.02)
    p.add_argument("--dry-run", action="store_true", default=True)
    p.add_argument("--live", dest="dry_run", action="store_false")
    p.add_argument("--queue", default=os.path.expanduser("~/code/lisbon-av-install/breath/say_queue.jsonl"))
    p.add_argument("--voice", default=VOICE)
    p.add_argument("--rate", type=int, default=100)
    p.add_argument("--ingestion", type=float, default=75.0)
    p.add_argument("--holding", type=float, default=180.0)
    p.add_argument("--explosion", type=float, default=50.0)
    p.add_argument("--speed", type=float, default=1.0)
    p.add_argument("--no-hum", dest="hum", action="store_false", default=True)
    p.add_argument("--no-murmur", dest="murmur", action="store_false", default=True)
    p.add_argument("--murmur-every", type=float, default=6.0)
    run(p.parse_args())

if __name__ == "__main__":
    main()
