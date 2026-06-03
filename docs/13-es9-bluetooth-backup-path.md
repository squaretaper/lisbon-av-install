# ES-9 → iLoud over Bluetooth (backup audio path)

## Why this exists

The intended signal chain is:

```
rack → ES-9 ins 1/2 → analog cables → iLoud Micro-Monitor inputs
```

If those analog cables are missing in the field, this is the substitute:

```
rack → ES-9 ins 1/2 → CoreAudio → Bluetooth → iLoud Micro-Monitor
```

A Python passthrough using `sounddevice` reads stereo from ES-9 inputs 1 & 2 and sends it to the system default output, which we set to the Bluetooth-paired iLouds.

## Trade-offs you must accept before using this

- **Bluetooth latency: 100–300 ms**, depending on AAC/SBC codec, distance, and interference. The install's reactive arc — lights and CV responding to room movement — runs at near-zero latency. Percussive or transient audio against zero-latency lights will feel **off**. Drone/ambient passes will feel fine.
- **Conflicts with the SWN bridge.** The bridge holds ES-9 open for both input *and* output. CoreAudio does not share USB audio interfaces well across processes. Pick one at a time.

## Operating it

Stop the SWN bridge LaunchAgent first:

```bash
launchctl bootout gui/$(id -u)/ai.ganchitecture.lisbon-swn-bridge
```

Run the passthrough in the foreground:

```bash
audio/run_es9_to_default_output.sh
```

It logs peak + RMS every 5 s so you can confirm signal. `Ctrl-C` stops it. Restore the SWN bridge with:

```bash
scripts/install-launchagents.sh
```

## Environment overrides

| Variable | Default | What it does |
|---|---|---|
| `LISBON_BT_INPUT_DEVICE` | `ES-9` | sounddevice substring for the input |
| `LISBON_BT_OUTPUT_DEVICE` | `iLoud` | sounddevice substring for the output |
| `LISBON_BT_LEFT` | `1` | ES-9 input channel for L |
| `LISBON_BT_RIGHT` | `2` | ES-9 input channel for R |
| `LISBON_BT_SR` | `48000` | sample rate |
| `LISBON_BT_BLOCK` | `256` | block size (larger = lower CPU, more latency; BT path is already 100–300 ms so 256 is fine) |
| `LISBON_BT_GAIN` | `0.6` | input gain before clip |

## Diagnosing "no signal"

If the peak/RMS report stays at `0.0000`, audio isn't reaching ES-9 inputs 1/2 at all. The script then reports silence to BT, which is exactly what you don't want.

Verified during build (2026-06-03): with the rack believed to be patched, all 16 ES-9 input channels read 0.0 RMS. Causes in likelihood order:

1. ES-9 front-panel routing is in a mode that doesn't surface analog ins to the USB host. Confirm the mode selector.
2. Source module is unpatched or silent.
3. CoreAudio negotiated a different alt-setting on the ES-9 USB descriptor; unplug and replug the USB to force renegotiation.

`sounddevice.query_devices()` (visible at the top of the script's startup output) will at minimum confirm the device is enumerated as a 16-in interface.

## Why this is a "temporary patch"

It is. The show config is analog cables, ES-9 outs → iLoud ins. This module exists for the case where field reality (a missing cable, a damaged jack, a Friday afternoon hardware store) is in the way. Move back to the analog path the moment cables exist.
