# Lisbon AV install — runtime config snapshot

Captured 6/4 opening day, after all live tuning was complete.

## Layout

```
config/
├── presets/
│   └── lisbon-opening-night.json   # tune.json values that drive the bridge
└── launchagents/                    # the five LaunchAgents running the install
    ├── ai.ganchitecture.lisbon-swn-bridge.plist          # main audio + CV
    ├── ai.ganchitecture.lisbon-realtime-chord-driver.plist  # chord layer
    ├── ai.ganchitecture.lisbon-esp32-sync.plist          # LED bridge
    ├── ai.ganchitecture.lisbon-camera-probe.plist        # Anker C200 HTTP server
    └── ai.ganchitecture.lisbon-audio-probe.plist         # mic probe
```

## How the live system was actually configured

### Hot-tunable knobs (audio/runtime/tune.json)

Polled by the bridge once per second, no restart needed. The
`config/presets/lisbon-opening-night.json` snapshot captures the
values that produced opening night's sound + light feel:

```json
{
  "movement_source": "extension_or_velocity",
  "glitch_fire_threshold": 0.3,
  "cv7_hold_ms": 0.0,
  "cv7_release_ms": 150.0,
  "browse_rate_min_hz": 0.009,
  "browse_rate_max_hz": 0.05
}
```

Re-apply after a clean checkout:

```sh
cp config/presets/lisbon-opening-night.json audio/runtime/tune.json
```

Or use the tuner script directly:

```sh
python3 scripts/tune.py \
    movement_source=extension_or_velocity \
    glitch_fire_threshold=0.30 \
    cv7_hold_ms=0 \
    cv7_release_ms=150 \
    browse_rate_min_hz=0.009 \
    browse_rate_max_hz=0.050
```

### LaunchAgent env overrides (in the .plist files)

- `LISBON_YOLO_MODEL=yolo11n-pose.pt` on the bridge — pose model
  used so arm extension and gesture-keypoint motion both have a
  signal to compute.
- `LISBON_CAMERA_URL=http://127.0.0.1:8765/frame.jpg` on the
  bridge — camera probe is the local HTTP shim.

### What the runtime values mean

- `movement_source = extension_or_velocity` — CV7 fires on max(arm
  reach beyond shoulder line, fast keypoint motion). Top-down
  camera friendly (the pure pose_raise wrist-above-elbow check
  collapses under foreshortening).
- `glitch_fire_threshold = 0.30` — anything below 30% gets gated,
  so walking does not fire CV7. A deliberate arm raise or a wave
  crosses this and slams CV7 to max_cv.
- `cv7_hold_ms = 0` + `cv7_release_ms = 150` — instant snap on
  trigger, ~150ms exponential decay back to silent. Tight, responsive.
- `browse_rate_*` halved from defaults (0.018..0.10 → 0.009..0.050)
  for a more glacial CV4 wavetable browse, matching the dirge tempo.

### Proximity-driven white bloom (no runtime knob, lives in source)

Chase + glitch modes get a pure-white overlay scaled by
`(1 - nearest_distance)^2` and gated on `people_count > 0`.
Empty room = pure red. Person right under the rig = ~50% white
bleed on top of the red. See `lighting/lisbon_esp32_soundscape_sync.py`
for the formula and `firmware/dual_strip_dystopia_test/src/main.cpp`
for the final-pass blend.

## Restoring on a new machine

1. Clone repo, install deps.
2. `cp config/presets/lisbon-opening-night.json audio/runtime/tune.json`
3. `cp config/launchagents/*.plist ~/Library/LaunchAgents/`
4. Adjust the hard-coded `/Users/ganchitecture` paths in the plists.
5. `launchctl load ~/Library/LaunchAgents/ai.ganchitecture.lisbon-*.plist`
6. Flash ESP32 firmware: `cd firmware/dual_strip_dystopia_test && pio run -t upload`

The bridge will fetch `yolo11n-pose.pt` on first detect call (~6MB).
