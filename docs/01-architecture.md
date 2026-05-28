# Architecture — Lisbon AV Install v6

## One-sentence concept

A room-scale installation where bodies moving through spatial sectors modulate a hardware wavetable chord in Eurorack, while the Mac mini realtime bridge listens to the rack return, generates/processes the main stereo mix through the ES-9, drives reactive LED light, and optionally accepts slow reflective heuristic updates.

## System diagram

```text
                ┌─────────────────────────────┐
                │         Mac Studio           │
                │       prototype phase        │
                └──────────────┬──────────────┘
                               │ transfer once stable
                               ▼
┌────────────────────────────────────────────────────────────────┐
│                         Mac mini, Lisbon                       │
│                                                                │
│  ┌─────────────────┐      WS       ┌────────────────────────┐  │
│  │ Python CV worker│──────────────▶│ Node/TS server          │  │
│  │ YOLOv8+ByteTrack│ tracks        │ sector aggregation      │  │
│  │ Anker C200      │              │ CV output scheduler     │  │
│                                   │ ES-9 audio listener     │  │
│                                   │ analyser + light derive │  │
│                                   │ main mix / FX           │  │
│                                   │ ESP32 WebSocket server  │  │
│                                   └─────┬───────────┬────────┘  │
│                                         │           │           │
│  ┌─────────────────────────────┐        │           │           │
│  │ Reflective agent sidecar    │◀───────┘           │           │
│  │ reviews telemetry minutes   │ status/profile    │           │
│  │ writes bounded heuristics   │                    │           │
│  └─────────────────────────────┘                    │           │
│                                         │ USB       │ WiFi/WS   │
└─────────────────────────────────────────┼───────────┼──────────┘
                                          │           │
                                          ▼           ▼
                                  ┌────────────┐  ┌──────────────┐
                                  │ ES-9       │  │ ESP32 LED    │
                                  │ CV out 1-8 │  │ controller   │
                                  │ audio in   │  │ WS2811 J1/J2 │
                                  │ main out   │  │              │
                                  └─────┬──────┘  └──────┬───────┘
                                        │ CV             │ data + 12V
                                        ▼                ▼
                         ┌────────────────────────┐  ┌────────────┐
                         │ Eurorack Palette 62    │  │ LED strips │
                         │ SWN + VCAs + utilities │  │ in gallery │
                         │ audio → ES-9 input     │  └────────────┘
                         │ bypass direct optional │
                         └───────────┬────────────┘
                                     ▼
                              Mixer / Genelecs
```

## Roles

### Mac Studio

Development and prototype machine. Use it to prove the ES-9, camera, server, ESP32, and rack patch before the Mac mini becomes the install box.

### Mac mini

Gallery machine. It should run the same repo/config as the Mac Studio with only machine-specific config changed: device names, network IPs, secrets, and launch/startup wrappers.

### CV worker

Runs local person detection/tracking. Publishes tracks; does not own musical logic.

### Node/TypeScript server / realtime bridge

Owns the fast loop:

- sector aggregation and smoothing
- CV scheduling to ES-9
- audio listener/analyser
- main mix / FX output to ES-9 outputs 1/2
- light derivation
- ESP32 WebSocket
- optional PWA endpoints
- telemetry/watchdogs

It must remain deterministic and locally safe. Any Max/MSP, PortAudio, DAW, or Python bridge used for realtime I/O should follow the same contract: perform audio/CV/light behavior immediately, never wait on an LLM or network call.

### Reflective agent sidecar

Owns the slow loop. It reads telemetry/status over minutes and writes a small bounded `heuristic_profile` for the realtime bridge to consume. It may adjust mode bias, sensitivity, density, silence/rest bias, light ceilings, glitch probability, or CV scaling within pre-approved clamps. It must not write live audio buffers, change ES-9 channel maps, alter patch destinations, edit code during show, or block the fast loop. See `10-reflective-agent-loop.md`.

### ES-9

The bridge between computer and rack:

- CV outputs drive VCA/modulation inputs.
- Audio inputs return the rack signal to the computer for realtime listening/processing/light derivation.
- Main 1/4" outputs carry the Mac stereo main mix to mixer/Genelecs in software performance mode.
- Stereo Line Out 1U / ES-9 internal mixer direct monitoring remain hardware bypass paths if the software audio path fails.

### Eurorack / SWN

The synthesis voice. SWN produces the chord/texture. VCAs and SWN CV inputs make the room activity audible.

### ESP32 controller

Receives light frames over WebSocket and drives two WS2811 channels through AHCT125-level-shifted data outputs.

## Non-negotiables

- No visitor registration flow.
- No per-person identity/signature binding.
- No database for v1.
- No browser-only/software-only synth replacing SWN as the primary rack voice.
- No CV updates at audio rate.
- No fixed camera thresholds that assume one frame height forever.
- No external 5 V backfeed into ESP32 VIN.
- No common-positive or rail mix-up: 12 V LED rail and USB-derived 5 V logic rail remain isolated.
- No LLM/agent call inside the realtime audio/CV/light reflex loop.
- No unbounded agent-authored parameters touching audio gain, CV voltage, brightness, channel maps, or serial command rate.

## Signal philosophy

The installation should be legible: bodies affect sectors; sectors affect voices; voices produce rack sound; the Mac realtime bridge hears/reshapes/responds; the resulting sound informs light. Keep the feedback loop perceivable, gain-staged, and bypassable.

The agentic layer should behave like metabolism rather than reflex: it reviews recent behavior and changes the envelope of the system, while the local realtime bridge performs safely within that envelope.
