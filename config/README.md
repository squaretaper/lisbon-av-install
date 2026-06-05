# Lisbon AV install — runtime config snapshot

Latest snapshot: **6/5 day 2** — captures the pose-raise upgrade after the camera angle vs. keypoint quality problem was resolved by switching to yolo11s-pose.

Earlier snapshots remain in `presets/` for rollback.

## Layout

```
config/
├── presets/
│   ├── lisbon-day-2-pose-raise.json   # current live state (6/5)
│   └── lisbon-opening-night.json      # opening-night baseline (6/4)
└── launchagents/                      # the five LaunchAgents running the install
    ├── ai.ganchitecture.lisbon-swn-bridge.plist          # main audio + CV
    ├── ai.ganchitecture.lisbon-realtime-chord-driver.plist  # chord layer
    ├── ai.ganchitecture.lisbon-esp32-sync.plist          # LED bridge
    ├── ai.ganchitecture.lisbon-camera-probe.plist        # Anker C200 HTTP server
    └── ai.ganchitecture.lisbon-audio-probe.plist         # mic probe
```

## Current live state (6/5)

### Hot-tunable knobs (audio/runtime/tune.json)

Polled by the bridge once per second, no restart needed:

```json
{
  "movement_source": "pose_raise",
  "glitch_fire_threshold": 0.05,
  "cv7_hold_ms": 200.0,
  "cv7_release_ms": 150.0,
  "browse_rate_min_hz": 0.009,
  "browse_rate_max_hz": 0.05,
  "postural_confidence_floor": 0.55,
  "postural_ema_alpha": 1.0
}
```

Re-apply after a clean checkout:

```sh
cp config/presets/lisbon-day-2-pose-raise.json audio/runtime/tune.json
```

### LaunchAgent env overrides (in the .plist files)

- `LISBON_YOLO_MODEL=yolo11s-pose.pt` — small pose model. yolo11n could
  not localize upper-body keypoints at this ceiling-down camera angle
  (wrists/elbows at 0.04-0.27 confidence). 11s sees them at 0.85-0.99.
  ~40ms inference on M4 mini, plenty of headroom under 100ms budget.
- `LISBON_CAMERA_HZ=10` — bumped from default 5Hz once 11s proved fast
  enough. Halves the inference latency floor for gesture detection.
- `LISBON_CAMERA_URL=http://127.0.0.1:8765/frame.jpg` — local camera
  probe HTTP shim.

### What the runtime values mean

- `movement_source = pose_raise` — CV7 fires whenever a wrist projects
  above the matching elbow in image coordinates. Works at any camera
  angle the bridge sees the joints from.
- `glitch_fire_threshold = 0.05` — any visible wrist-above-elbow fires.
  With reliable keypoints there is no jitter floor to gate against;
  the function naturally returns 0 when arms hang.
- `cv7_hold_ms = 200` + `cv7_release_ms = 150` — 200ms full hold then
  150ms exp decay. Hold smooths over single-frame detection blinks
  during sustained gestures.
- `postural_ema_alpha = 1.0` — EMA disabled. With reliable keypoints
  from yolo11s, single-frame smoothing was adding latency without
  rejecting any real noise.
- `browse_rate_*` from opening-night baseline preserved.

### Architectural fixes that landed during day 2

- **PR #61** centroid-teleport velocity guard — drops CV7 fires from
  tracker identity swaps.
- **PR #62** wrist-elevation postural feature (`elevation_or_velocity`)
  + EMA infrastructure + new tune knobs. Not currently the active
  source but available.
- **PR #63** mode 1 all white, mode 2 pure red. Inverted the earlier
  red-baseline-with-white-bloom design.
- **PR #64** yolo11s-pose model upgrade.
- **PR #65** `scene.movement = max(tracks.movement)` not weighted
  average — phantom tracks no longer dilute real gestures.

### Proximity-driven brightness lift (no runtime knob, lives in source)

Chase mode (white) brightness lifts as people approach. Empty room
sits at CV6 idle brightness. See `lighting/lisbon_esp32_soundscape_sync.py`.

## Restoring on a new machine

1. Clone repo, install deps.
2. `cp config/presets/lisbon-day-2-pose-raise.json audio/runtime/tune.json`
3. `cp config/launchagents/*.plist ~/Library/LaunchAgents/`
4. Adjust the hard-coded `/Users/ganchitecture` paths in the plists.
5. `launchctl bootstrap gui/$UID ~/Library/LaunchAgents/ai.ganchitecture.lisbon-*.plist`
6. Flash ESP32 firmware: `cd firmware/dual_strip_dystopia_test && pio run -t upload`

The bridge will fetch `yolo11s-pose.pt` on first detect call (~19MB).

## Refreshing LaunchAgent env after editing a plist

`launchctl kickstart` does NOT pick up env changes. To reload env vars
(e.g. when bumping `LISBON_CAMERA_HZ` or swapping the YOLO model):

```sh
launchctl bootout gui/$UID/ai.ganchitecture.lisbon-swn-bridge
launchctl bootstrap gui/$UID ~/Library/LaunchAgents/ai.ganchitecture.lisbon-swn-bridge.plist
```
