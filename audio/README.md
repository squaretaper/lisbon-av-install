# Lisbon SWN camera soundscape

Realtime bridge for the current hardware patch:

```text
SWN / modular main mix -> ES-9 physical inputs 1+2 -> Mac/CoreAudio inputs 1+2
Mac/CoreAudio outputs 1+2 -> ES-9 main mix path / 1/4" main outs
Camera bridge /frame.jpg -> YOLO+ByteTrack -> Python mapper -> ES-9 physical CV outs 1-8
```

## Current CV patch map

ES-9 physical 3.5 mm CV outputs are CoreAudio outputs 9-16 by default.

| Physical CV | CoreAudio out | Destination |
|---:|---:|---|
| CV1 | 9 | SWN voice 1 1V/oct |
| CV2 | 10 | SWN voice 2 1V/oct |
| CV3 | 11 | SWN voice 3 1V/oct |
| CV4 | 12 | SWN wavetable browse |
| CV5 | 13 | SWN dispersion |
| CV6 | 14 | SWN dispersion pattern |
| CV7 | 15 | O&C glitch logic/gate input: smoothed room-movement CV |
| CV8 | 16 | SWN depth |

Pitch CVs are intentionally conservative: a fixed root/fifth/octave-ish chord with only tiny camera/person drift. The noisier visitor response goes to browse/dispersion/pattern/depth, while CV7 is reserved for the repatched O&C glitch gate and stays low unless the room is actually moving.

## Vision modes

Default live mode is now `--vision-mode people`:

- pulls frames from the native camera bridge at `http://127.0.0.1:8765/frame.jpg`,
- runs Ultralytics YOLO (`yolo11n.pt`) with ByteTrack,
- extracts stable person count, ID, approximate distance, spread, movement, and activity,
- maps those human-scene features gradually into the SWN CVs,
- writes an annotated preview to `audio/runtime/swn_camera_people_preview.jpg`.

Fallback/prototype mode is still available with `--vision-mode aggregate`; it uses frame brightness, frame-difference motion, and visual centroid without person detection.

The status JSON includes `person_scene` plus selected ES-9 input-pair RMS/peak/frequency/glitch telemetry in `audio_input`. `audio_input.source_input_channels` records the 1-based CoreAudio input pair currently being monitored/routed. Frequency/glitch analysis includes both zero-crossing and FFT-band features (`dominant_frequency_hz`, `spectral_centroid_hz`, `low_band_ratio`, `mid_band_ratio`, `high_band_ratio`) so lighting can distinguish low drones from high-frequency glitches.

## Agentic architecture note

Keep the live bridge as the fast deterministic loop. Camera/audio analysis should immediately map to bounded CV, audio, and lighting behavior without waiting on any LLM/agent call. If an agentic layer is added, it should review recent status/log windows every few minutes and write an advisory `audio/runtime/heuristic_profile.json` with bounded parameters only; `audio/heuristic_profile.example.json` documents the shape. The bridge must ignore missing, malformed, expired, or out-of-range profiles and continue with safe defaults. See `docs/10-reflective-agent-loop.md`.

## ES-9 config notes

The 2026-05-25 hosted config screenshot showed the important input side appears right: physical `Input 1 -> USB audio 1` and `Input 2 -> USB audio 2`, so the Mac should see the rack return on CoreAudio inputs 1/2. If ES-9 and a known microphone both enumerate but read digital zero, check macOS Microphone/TCC for the responsible Python/venv binary before changing ES-9 routing. After granting TCC microphone access, ES-9 inputs 1/2 produced nonzero live RMS/peak telemetry and now drive lighting directly.

To hunt for a signal on any ES-9 input channel:

```bash
# status file written by the live probe when running:
audio/runtime/es9_input_probe_status.json
```

If the signal lands on a pair other than 1/2, run the bridge with `--input-left-channel N --input-right-channel M` (or `LISBON_INPUT_LEFT_CHANNEL` / `LISBON_INPUT_RIGHT_CHANNEL` in the wrapper) so the Mac listens to and routes the actual return pair.

For the audible return path, this bridge writes the stereo main mix on CoreAudio outputs 1/2. In the visible ES-9 config those are routed through the internal mixer as `USB 1/2 -> Mix 1/2 -> Main Out L/R`, not directly to the 3.5mm CV outputs. If the main return is too quiet, raise the `USB 1/2` fader in `Mix 1/2 : Main Out L/Main Out R` toward unity. Keep `USB 1/2` muted in `Mix 5/6 : Output 1/Output 2` to avoid audio bleed onto physical CV outputs 1/2 while CoreAudio outputs 9/10 are carrying CV1/CV2.

## Run

From the project root:

```bash
audio/run_swn_camera_soundscape.sh
```

The wrapper uses conservative live defaults:

```text
LISBON_MAIN_GAIN=0.35
LISBON_INPUT_LEFT_CHANNEL=1
LISBON_INPUT_RIGHT_CHANNEL=2
LISBON_MAX_CV=0.18
LISBON_VISION_MODE=people
LISBON_CAMERA_HZ=2
LISBON_STATUS_HZ=60
LISBON_BLOCKSIZE=128
LISBON_STILLNESS_DEADBAND=0.03
LISBON_STILLNESS_FRAME_MOTION=0.03
LISBON_PREVIEW_HZ=1
```

Override if needed:

```bash
LISBON_MAIN_GAIN=0.45 LISBON_MAX_CV=0.22 audio/run_swn_camera_soundscape.sh
```

Equivalent direct command:

```bash
. .venv-lisbon-audio/bin/activate
python audio/lisbon_swn_camera_bridge.py \
  --camera-url http://127.0.0.1:8765/frame.jpg \
  --device ES-9 \
  --vision-mode people \
  --camera-hz 2 \
  --status-hz 60 \
  --blocksize 128 \
  --stillness-deadband 0.03 \
  --stillness-frame-motion 0.03 \
  --main-gain 0.35 \
  --input-left-channel 1 \
  --input-right-channel 2 \
  --max-cv 0.18 \
  --preview-path audio/runtime/swn_camera_people_preview.jpg
```

Status JSON is written to:

```text
audio/runtime/swn_camera_soundscape_status.json
```

For a non-audio check that only exercises camera -> CV mapping:

```bash
. .venv-lisbon-audio/bin/activate
python audio/lisbon_swn_camera_bridge.py --dry-run --duration 5
```

## Stop

Press Ctrl-C, or kill the process. On exit/stall the ES-9 will stop receiving the generated DC stream; for performance use we should add a LaunchAgent/supervisor once the mapping feels right.
