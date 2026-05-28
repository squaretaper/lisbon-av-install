# Phases — Prototype to Lisbon Install

## Phase 0 — Inputs and runtime stability

Status: done for this doc pass.

- Runtime instability was fixed before continuing docs.
- Source docs and schematic were archived under `../inputs/`.
- v6 docs were split into focused files.

## Phase 1 — Mac Studio feasibility gates

Goal: prove the three risky foundations before building the full system.

### Gate 1: ES-9 CV output from Node/server

Minimum test:

- Open ES-9 as multichannel output.
- Write a steady DC value to one physical ES-9 CV output.
- Verify with meter/scope.
- Optional: patch to SWN 1V/oct input in pitch mode and verify expected pitch movement.

Acceptance:

- The output is stable for at least 10 seconds.
- Channel mapping is documented.
- Voltage scaling is measured and written to `tunings.json`.

### Gate 2: ES-9 full-duplex agent audio path

Minimum test:

- Patch a known signal into ES-9 input 1 or stereo inputs 1+2.
- Read in Node/server or chosen audio engine and log RMS/peak/FFT values.
- Simultaneously send a low-level stereo main-mix placeholder to ES-9 outputs 1/2 / 1/4" main outs.
- Confirm zero/low reading when disconnected and sane nonzero reading when patched.
- While audio I/O runs, hold/update all 8 ES-9 CV outputs to prove the real performance load.

Acceptance:

- Levels are stable enough for listening/FX/light derivation.
- Input, main-output, and CV-output channel mappings are documented.
- Audible output comes from the intended Mac/agent path with no feedback loop.
- Failure mode and bypass route are known if device/audio engine disconnects.

### Gate 3: CV tracking in dim conditions

Minimum test:

- Anker C200 in dim gallery-like lighting.
- YOLOv8n or equivalent + ByteTrack.
- Test at 5–10 m.
- Publish tracks at 10–30 Hz.

Acceptance:

- Track IDs are stable enough for sector activity.
- False positives/ghosts are acceptable or filtered.
- Sector bins respond to walking through the room.

## Phase 2 — Hardware build in NYC

- Build ESP32/LED controller in enclosure.
- Correct D1/reverse-polarity strategy before final assembly.
- Verify 12 V/5 V rail isolation and common ground.
- Run USB-only ESP32 test.
- Run 12 V no-load power test.
- Run low-brightness LED test.
- Photograph and label all wiring.

## Phase 3 — Rack patch on Mac Studio

- Install/verify Palette 62 modules.
- Confirm ES-9 depth/standoff solution.
- Patch SWN voices to VCAs and output path.
- Set static pitches manually.
- Decide current VCA configuration: 6 VCA current state vs 8 VCA if second DVCA is found.
- Photograph the front and back of the patch.

## Phase 4 — Software integration on Mac Studio

Build in this order:

1. Server skeleton with `/health`, `/api/state`, `/ws/cv`, `/ws/esp`, `/ws/admin`.
2. CV worker publisher.
3. Sector aggregation and smoothing.
4. ES-9 CV scheduler with `cvMap` presets.
5. ES-9 audio listener + main-mix/FX output path.
6. Light derivation and ESP32 WebSocket frames.
7. Optional PWA: `/morph`, `/silence`, status page.
8. Telemetry and watchdogs.

## Phase 5 — Dry run

- Full system on Mac Studio.
- Rack audio through Mac/agent path to mixer/speakers, with hardware bypass verified.
- ESP32 drives real or test strip.
- Walk through sectors and verify audible changes.
- Test empty-room state.
- Test disconnect/reconnect of ESP32, CV worker, and ES-9.
- Confirm offline operation on travel-router WiFi.

## Phase 6 — Transfer to Mac mini

- Clone repo/config.
- Install dependencies.
- Verify device names and ES-9 channel mapping.
- Run all three Day 1 gates again on the Mac mini.
- Run full dry run from Mac mini.
- Create launch/start script.

## Phase 7 — Lisbon install

- Receive Mac mini and LED strips.
- Inspect rack/enclosure after travel.
- Recreate patch from photos if needed.
- Set up travel router.
- Mount camera.
- Run power checks before connecting strips.
- Calibrate sectors to actual gallery.
- Tune CV ranges and morph states.
- Run a full show-length soak test.

## Phase 8 — Show operation

- Daily startup check.
- Monitor telemetry.
- Keep kill switch available.
- Photograph final setup.
- End with controlled shutdown.
