# Lisbon AV Install v6 Documentation Index

This is the re-audited v6 doc set for a Lisbon real-time audio-visual gallery installation.

The source inputs are not part of this public source bundle. Treat this `docs/` directory as the current working canon.

## Canonical direction

**v6 = v5-B cleaned up:** spatial sectoring + modular hardware synthesis.

Current runnable source in this public snapshot is the hardware-facing path: native macOS camera bridge, Python/CoreAudio ES-9 CV/audio bridge, Python ESP32 serial-lighting bridge, PlatformIO ESP32 firmware, and audited LED-controller schematics. Some docs still describe the broader server/PWA architecture as a future consolidation target.

- Prototype on the development Mac.
- Transfer the stable build to the Mac mini for Lisbon.
- Use CV tracking to divide the room into sectors.
- Send smoothed sector activity to the ES-9 as CV.
- Use the Eurorack/SWN as the synthesis voice.
- Read ES-9 audio return for realtime bridge listening/light derivation, and send the Mac stereo main mix back to the ES-9 1/4" main outs.
- Drive two WS2811 LED channels from the ESP32 controller.
- Optional PWA is a minimal morph/silence/status interface, not a visitor-registration system.
- Keep AI/agent reasoning out of the realtime reflex arc: deterministic fast loop for audio/CV/lights, slow reflective loop for bounded heuristic updates.

## Read order

1. `01-architecture.md` — system shape and non-negotiables.
2. `02-phases.md` — phase plan from Mac Studio prototype to Lisbon install.
3. `03-hardware-electrical.md` — ESP32, PSU, LEDs, rail isolation, checks.
4. `04-eurorack-es9-swn.md` — rack patch, ES-9 CV/audio, SWN behavior.
5. `05-software-cv-server.md` — server/API schema for the broader architecture; current runnable bridge code lives in `audio/`, `cv/`, and `lighting/`.
6. `06-esp32-firmware-lighting.md` — firmware and light protocol.
7. `07-mac-studio-to-mac-mini-transfer.md` — transfer and reproducibility.
8. `08-lisbon-install-runbook.md` — on-site setup/run/shutdown.
9. `09-risk-register.md` — risks and mitigations.
10. `10-reflective-agent-loop.md` — fast reflex / slow agentic metabolism architecture.

## Day 1 gating tests

These must pass before deep implementation:

1. **ES-9 CV output from the Python/CoreAudio bridge** — write a stable DC voltage to a physical ES-9 CV output and verify with scope/meter or SWN response.
2. **ES-9 full-duplex audio path** — read SWN/test signal from ES-9 inputs 1+2, send controlled stereo main mix to ES-9 outputs 1/2, and hold/update all 8 CV outputs simultaneously.
3. **CV tracking in dim gallery-like conditions** — YOLOv8 + ByteTrack tracks bodies at 5–10 m with acceptable stability.

If gate 1 or 2 fails, pivot early instead of building weeks of software around an unreliable I/O path.
