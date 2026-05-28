# Eurorack, ES-9, and SWN

## Rack goal

Use the Palette 62 as a compact hardware synthesis engine with the Mac mini/agent as an active performer. SWN supplies the rack voice. ES-9 supplies bidirectional audio/CV: rack audio into Mac, Mac/agent stereo main mix back out, and Mac CV/control to the rack.

## Current Palette 62 plan

Main row, 62 HP:

| Module | HP | Role |
|---|---:|---|
| Expert Sleepers ES-9 | 16 | USB audio/CV bridge |
| 4ms SWN | 26 | six-voice wavetable synth |
| Intellijel Quad VCA | 12 | VCA control for voices/modulation |
| Ornament + Crime | 8 | utility/modulation/helper |

1U row:

- Stereo Line Out 1U for hardware bypass / direct rack → mixer output.
- Quadratt 1U for attenuation/mixing.
- DVCA 1U modules if available for extra VCA count.

## Audio topology

Primary / artistic path — agent performance mode:

```text
SWN stereo out → optional hardware FX → ES-9 inputs 1+2 → Mac mini agent/audio engine
                                                       → ES-9 1/4" main outs → mixer → Genelecs
                                                       └→ analyser/listening loop → lights/CV/morph responses
Mac mini → ES-9 3.5mm DC-coupled outputs 1-8 → rack CV/control
```

Hardware bypass / degraded fallback:

```text
SWN stereo out → optional hardware FX → Stereo Line Out 1U → mixer → Genelecs
# or
SWN stereo out → optional hardware FX → ES-9 inputs 1+2
                                      → ES-9 internal mixer/direct monitor → ES-9 1/4" main outs → mixer
```

Agent performance mode intentionally puts the Mac in the main audio path so it can hear and respond to the music it is playing. The bypass path remains for safety if software routing, gain staging, latency, or feedback behavior becomes unstable.

## CV topology

Use physical ES-9 CV outputs as the canonical labels. Software channel numbers may differ by driver/routing and must be calibrated.

Official ES-9 defaults to remember for the Mac/agent routing:

- ES-9 is a class-compliant USB 2.0 **16-in / 16-out** interface at 24-bit, 44.1/48/88.2/96 kHz.
- Hardware inputs 1-14 route to DAW/CoreAudio inputs 1-14 by default; for this install, the primary rack return uses hardware inputs 1+2, with inputs 3-14 available for extra stems/taps.
- Main 1/4" balanced outputs are DAW/CoreAudio outputs 1/2 by default and carry the audible Mac/agent stereo main mix.
- Physical 3.5mm DC-coupled outputs 1-8 are DAW/CoreAudio outputs 9-16 by default and carry CV/control signals.
- The ES-9 internal mixer can route hardware inputs directly to main outs while USB simultaneously streams audio to/from the Mac.
- USB bandwidth is not the limiting factor; channel mapping and software duplex routing are the real Day 1 tests.

### Current live SWN patch: camera soundscape prototype

The current patch for the first studio test uses the ES-9 physical 3.5mm CV outputs this way:

```json
{
  "preset": "swn_camera_soundscape_v1",
  "outputs": {
    "cv1": { "dest": "SWN voice 1 1V/oct", "source": "root pitch with tiny camera drift" },
    "cv2": { "dest": "SWN voice 2 1V/oct", "source": "fifth-ish pitch with tiny camera drift" },
    "cv3": { "dest": "SWN voice 3 1V/oct", "source": "octave-ish pitch with tiny camera drift" },
    "cv4": { "dest": "SWN Browse / wavetable position", "source": "camera centroid + activity" },
    "cv5": { "dest": "SWN Dispersion", "source": "camera motion" },
    "cv6": { "dest": "SWN Dispersion Pattern", "source": "camera vertical mass + activity" },
    "cv7": { "dest": "O&C glitch logic/gate input", "source": "smoothed room movement gate CV; low when still" },
    "cv8": { "dest": "SWN Depth", "source": "camera aggregate activity" }
  }
}
```

The current prototype implementation is `audio/lisbon_swn_camera_bridge.py`; it routes ES-9 inputs 1+2 to outputs 1+2 and writes physical CV1-CV8 on CoreAudio outputs 9-16.

### `cvMap` preset: six-VCA current build

```json
{
  "preset": "palette62_six_vca",
  "outputs": {
    "cv1": { "dest": "SWN voice 1 VCA", "source": "sector.nearLeft.activity" },
    "cv2": { "dest": "SWN voice 2 VCA", "source": "sector.nearRight.activity" },
    "cv3": { "dest": "SWN voice 3 VCA", "source": "sector.midFarLeft.activity" },
    "cv4": { "dest": "SWN voice 4 VCA", "source": "sector.midFarRight.activity" },
    "cv5": { "dest": "SWN voice 5 VCA", "source": "bed.level" },
    "cv6": { "dest": "SWN voice 6 VCA", "source": "bed.levelOffset" },
    "cv7": { "dest": "SWN Browse / wavetable position", "source": "movement.aggregate" },
    "cv8": { "dest": "O_C or FX modulation", "source": "morph.global" }
  }
}
```

### `cvMap` preset: eight-VCA build

If the second DVCA 1U is found and installed, CV1-CV6 can map 1:1 to six voice VCAs and CV7/CV8 remain global modulation.

## Voice pitches

Set SWN pitches manually during the NYC patch/install composition step. Do not attempt to morph pitch in v1 if the SWN jacks are being used as VCA inputs.

Default starting chord from source plan:

```text
C2, G2, C3, Eb3, G3, C4
```

Treat this as a musical starting point, not a protocol requirement.

## CV scaling

The source docs use a normalized audio/CV convention where output offset `1.0` is approximately +10 V on the ES-9 after calibration. Under that convention:

- `0.1` normalized offset ≈ +1 V.
- At 1 V/oct, `0.1` normalized offset ≈ one octave.
- One semitone ≈ `0.008333` normalized offset.

This corrects the stale note that said `0.1` was one semitone.

For VCA/modulation use, ignore pitch math and calibrate empirically:

- Start 0–3 V for VCA CV.
- Increase toward 0–5 V only if useful and safe.
- Use Quadratt/attenuation if ES-9 range is too wide.
- Ramp changes over 100–300 ms for musical smoothing.
- Update at 20–30 Hz, never audio rate.

## Day 1 ES-9 tests

### CV out

- Route one constant source to a known ES-9 physical 3.5mm CV output.
- Use default hosted/CoreAudio mapping as the starting assumption: physical 3.5mm outputs 1-8 are outputs 9-16.
- Measure 0.0, 0.1, 0.25, 0.5 normalized offsets.
- Record measured voltages in `tunings.json`.
- Confirm no DC drift or surprise channel swap.

### Full-duplex agent audio path

- Patch a known signal into ES-9 input 1, then a stereo rack/SWN return into ES-9 inputs 1+2.
- Simultaneously send a low-level stereo test tone/noise/main-mix placeholder to ES-9 outputs 1/2 / 1/4" main outs.
- Verify RMS/FFT/listening-loop data updates when SWN plays and decays when muted.
- Verify the audible output comes from the intended Mac/agent path and that there is no feedback loop.
- While audio I/O runs, hold/update all 8 CV outputs so we prove audio-in + main-out + CV-out together.

## Morph states

Morph states may change:

- SWN browse/depth/latitude/longitude/dispersion if patched/CV-controllable.
- CV modulation scale.
- LFO/modulation speed range.
- Hardware FX modulation.
- Software-side light mapping.

Morph states may not automatically change:

- SWN Sphere selection, unless a human physically changes it.
- Voice pitches, unless the patch topology is redesigned.
- SWN preset recall, because SWN has no such software control path in this plan.

Do not include “change Sphere at midpoint” as an automated behavior in v6.
