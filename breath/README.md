# breath — the Lisbon monolith (breathwork + voice + arrival)

A standalone, additive layer over the `lisbon-av-install` rig. It makes the obelisk
*breathe, hum, speak, and arrive* — driving the ESP32 red strips (serial) and the
voice (ES-9 out 8). Does not touch the soundscape bridge's code; it just takes the
serial port + an ES-9 output while running.

## Pieces
- **`breath_clock.py`** — the core. A transcendent triangle breath (inhale → long hold →
  slow dissolve, never strobes/blacks out) on the strips; a deep continuous hum; near-
  constant commentary in **extreme shifting registers** (boom / whisper / frantic / sub /
  garbled / sweeps); Close-Encounters voice replies from a queue; and a **Soul Train
  arrival** beat. All voice routes through `speak8.py` to ES-9 out 8. Sole owner of the
  serial port; survives USB re-enumeration (reopens instead of crashing).
- **`speak8.py`** — renders a line with macOS `say` and plays it to a specific ES-9
  channel (default ch16 = physical out 8) via `sounddevice`, applying optional `GARBLE`
  DSP (bit-crush + ring-mod). Non-blocking lock so overlaps drop.
- **`beat.py`** — synthesizes the "Soul Train arrival" (rising approach-sweep → kick/hat
  groove) with numpy and plays it to ES-9 out 8.
- **`oracle_bridge.py`** — HTTP receiver: `POST /oracle {ganchi_reply}` → appends to the
  voice queue so the monolith speaks chat replies (web-chat path).
- **`set_output.swift`** — offline CoreAudio helper to set the macOS default output device
  by name (no deps). `swiftc set_output.swift -o set_output -framework CoreAudio -framework Foundation`
- **`RESTORE-*.cmd`** — how to hand the strips / audio back to the soundscape bridge.

## Run
```bash
python3 -m venv .venv && ./.venv/bin/pip install sounddevice soundfile numpy   # py3.11+ ; coolledx (ticker) needs 3.11–3.12
# breath + hum + commentary + voice on ES-9 out 8:
python3 breath_clock.py --live --voice Daniel
# speak a line / trigger the train:
echo '{"text":"hello, traveler"}' >> say_queue.jsonl
echo '{"beat":true}'              >> say_queue.jsonl
```

## Queue contract (`say_queue.jsonl`, one JSON object per line)
- `{"text": "..."}` → spoken (deep HAL register) + a gentle light bloom. Embed
  `[[pbas]]/[[rate]]/[[volm]]/[[slnc]]`; prefix `GARBLE ` for the mangled register.
- `{"beat": true}` (or text `soul train` / `drop` / `arrival`) → the arrival beat + groove.

## Audio routing
Voice/beat play to **ES-9 out 8** (CoreAudio ch16) via channel-mapped `sounddevice`.
Patch ES-9 out 8 → the PA/VCA; level is rideable via the VCA / a software gain.

## Not yet wired
- **Ticker (CoolLED1248 panels)** — words/clock via the `coolledx` BLE driver (needs a
  Python 3.11/3.12 venv + the panel freed from the phone app).
- **Group → voice** — bridge the Telegram group to the queue for live call-and-response.
