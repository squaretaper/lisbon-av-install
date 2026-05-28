# Architecture — Lisbon AV Install v6

## One-sentence concept

A room-scale installation where bodies moving through spatial sectors modulate a hardware wavetable chord in Eurorack, while the Mac mini/agent listens to the rack return, generates/processes the main stereo mix through the ES-9, and drives reactive LED light.

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
│                                   │ agent main mix / FX     │  │
│                                   │ ESP32 WebSocket server  │  │
│                                   └─────┬───────────┬────────┘  │
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

### Node/TypeScript server

Owns state:

- sector aggregation and smoothing
- CV scheduling to ES-9
- audio listener/analyser
- agent main mix / FX output to ES-9 outputs 1/2
- light derivation
- ESP32 WebSocket
- optional PWA endpoints
- telemetry/watchdogs

### ES-9

The bridge between computer and rack:

- CV outputs drive VCA/modulation inputs.
- Audio inputs return the rack signal to the computer for agent listening/processing/light derivation.
- Main 1/4" outputs carry the Mac/agent stereo main mix to mixer/Genelecs in agent performance mode.
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

## Signal philosophy

The installation should be legible: bodies affect sectors; sectors affect voices; voices produce rack sound; the agent hears/reshapes/responds; the resulting sound informs light. Keep the feedback loop perceivable, gain-staged, and bypassable.
