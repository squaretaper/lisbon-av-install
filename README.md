# Lisbon AV Install

Public source bundle for a real-time Lisbon audio/visual installation: a macOS camera bridge watches the room, a Python/CoreAudio bridge turns camera and modular-audio features into Expert Sleepers ES-9 CV, and an ESP32 drives two red-only WS2811 LED channels from the analyzed soundscape.

This repo is organized as an implementation notebook plus runnable software. It keeps the active code, hardware-facing firmware, schematics, and runbooks together, but intentionally does **not** vendor local virtualenvs, runtime captures, YOLO model weights, or raw datasheet PDFs.

## System shape

```text
Anker C200 / AVFoundation camera
        -> cv/camera_probe (local HTTP /frame.jpg + MJPEG)
        -> audio/lisbon_swn_camera_bridge.py
        -> ES-9 outputs 9-16 = physical CV outs 1-8
        -> 4ms SWN / O&C / modular patch

SWN / modular stereo return
        -> ES-9 inputs 1/2
        -> Mac/CoreAudio analysis + pass-through
        -> ES-9 outputs 1/2 / main outs
        -> lighting/lisbon_esp32_soundscape_sync.py
        -> USB serial one-character protocol
        -> ESP32 + AHCT125 + two WS2811 red LED channels
```

## Repository map

| Path | Purpose |
|---|---|
| `audio/` | Python ES-9/CoreAudio bridge: stereo pass-through, audio telemetry, camera/person tracking, safe DC CV generation, and example reflective heuristic profile. |
| `lighting/` | Python bridge from audio/CV status JSON to ESP32 serial light commands. |
| `cv/camera_probe/` | Native macOS Swift/AVFoundation camera bridge packaged as a tiny GUI-session app for Camera/TCC permission. |
| `firmware/dual_strip_dystopia_test/` | Active ESP32/FastLED firmware for two WS2811 strips, pure red/black only, live serial controls. |
| `firmware/*_test/` | Bench sketches for status LED, J1 strip, red-chaos strip, and case light-pipe validation. |
| `docs/` | Architecture, ES-9/SWN patch map, reflective agent-loop architecture, ESP32 electrical notes, runbook, and risk register. |
| `docs/esp32-breadboard/` | Audited breadboard/perfboard pack, BOM, netlist, and wiring checklist. |
| `diagrams/` and `kicad/` | Generated schematic exports plus editable KiCad project files for the ESP32 LED controller. |
| `tests/` | Pure-Python tests for CV mapping, audio analysis, lighting decisions, and firmware invariants. |

## Realtime / reflective split

The live installation keeps agentic behavior out of the immediate audio/CV/light reflex path. The realtime bridge remains deterministic and local; any agent or reviewer reads telemetry over minutes and writes a bounded, expiring `heuristic_profile` for the fast loop to clamp or ignore. See `docs/10-reflective-agent-loop.md` and `audio/heuristic_profile.example.json`.

## Active patch map

Default ES-9 mapping assumes the class-compliant hosted/CoreAudio layout:

| Physical ES-9 output | CoreAudio out | Destination |
|---:|---:|---|
| CV1 | 9 | SWN voice 1 1V/oct, conservative fixed chord/tiny drift |
| CV2 | 10 | SWN voice 2 1V/oct |
| CV3 | 11 | SWN voice 3 1V/oct |
| CV4 | 12 | SWN wavetable browse |
| CV5 | 13 | SWN dispersion |
| CV6 | 14 | SWN dispersion pattern |
| CV7 | 15 | O&C movement/glitch logic gate input |
| CV8 | 16 | SWN depth |

The bridge keeps pitch CVs intentionally stable. Noisy features go to timbre/depth/movement first.

## Quick start: Python bridges

On a macOS install/prototype machine, first inventory the attached devices:

```bash
scripts/check-devices.sh
```

macOS with Homebrew Python is the intended runtime for the live ES-9 bridge.

```bash
python3 -m venv .venv
. .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

Dry-run the camera-to-CV mapper without opening the ES-9 stream:

```bash
python audio/lisbon_swn_camera_bridge.py --dry-run --duration 5
```

Run the live soundscape bridge with conservative defaults:

```bash
audio/run_swn_camera_soundscape.sh
```

Then run the ESP32 lighting sync against the status JSON:

```bash
python lighting/lisbon_esp32_soundscape_sync.py \
  --serial /dev/cu.usbserial-0001 \
  --status-path audio/runtime/swn_camera_soundscape_status.json \
  --interval 0.02 \
  --initial-mode 0 \
  --initial-brightness 64
```

## Quick start: camera bridge

Build the macOS app bundle:

```bash
scripts/build-camera-bridge.sh
```

Open it in the signed-in GUI session so macOS can grant Camera permission:

```bash
cv/camera_probe/LisbonCameraProbe.app/Contents/MacOS/LisbonCameraProbe \
  --port 8765 \
  --snapshot-path cv/captures/latest.jpg \
  --snapshot-interval 0.5 \
  --fps 10
```

Verify endpoints:

```bash
curl -s http://127.0.0.1:8765/status | python3 -m json.tool
curl -fsS http://127.0.0.1:8765/frame.jpg -o /tmp/lisbon-frame.jpg
```

## Quick start: ESP32 firmware

The active firmware is PlatformIO/Arduino:

```bash
cd firmware/dual_strip_dystopia_test
pio run
pio run -t upload
pio device monitor -b 115200
```

Serial protocol summary: `0` all red, `1` red chasing packets, `2` glitch strobe/fault cells, `3` running together, `4` low dystopian breath/scan, `x` blackout, `a` auto, `+/-` brightness, `>/<` chase speed, `]/[` pulse depth, `}/{` packet span, `?` status.

## Tests

```bash
python -m pip install -r requirements-dev.txt
pytest -q
```

The Swift camera bridge smoke test is a standalone script because it needs a built macOS app bundle:

```bash
scripts/build-camera-bridge.sh
python cv/tests/test_camera_bridge_mock_http.py
```

## Safety notes

- Start CV conservatively. In this repo, `1.0` normalized ES-9 output is treated as roughly `+10 V`; default live max CV is `0.18`.
- Do not send audio-rate signals to CV destinations unless intentionally patching that behavior.
- The active LED firmware is red-only by design: strip pixels are always `CRGB(red, 0, 0)` or black.
- Bench the ESP32/AHCT125/WS2811 wiring with current-limited power before gallery use.
- Raw datasheet PDFs and downloaded model weights are excluded from git; see `references/datasheets.md` and let Ultralytics download `yolo11n.pt` or provide your own model path.

## License

No open-source license has been selected yet. Public visibility does not grant reuse rights until a license is added.
