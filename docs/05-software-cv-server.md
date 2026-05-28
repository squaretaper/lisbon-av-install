# Software, CV Worker, Server, and Protocol

## Repo shape

```text
/firmware/      ESP32 PlatformIO project
/server/        Node TypeScript server
/cv/            Python CV worker
/docs/          this documentation
```

## Server responsibilities

- HTTP health/status endpoints.
- WebSocket endpoints for CV worker, ESP32, and optional admin dashboard.
- Sector aggregation and smoothing.
- ES-9 CV output scheduling.
- ES-9 audio input listening/analysis for light derivation.
- ES-9 stereo main-mix/FX output on outputs 1/2 for agent performance mode.
- Morph and silence controls.
- Telemetry/watchdogs.

## Endpoints

v6 endpoints:

- `GET /health` — simple process health.
- `GET /api/state` — current state snapshot.
- `POST /api/morph` — optional one-button morph trigger.
- `POST /api/silence` — kill switch; ramp CVs/lights to safe state.
- `WS /ws/cv` — CV worker publishes tracks.
- `WS /ws/esp` — ESP32 connects for light frames and heartbeat.
- `WS /ws/admin` — optional live monitor.

Removed from v6:

- `POST /api/register`
- visitor IDs/signatures/session tokens
- visitor database or per-person audio layers

## CV worker → server message

The worker may publish pixels and frame dimensions. The server must normalize before sectoring.

```json
{
  "type": "tracks",
  "timestamp": 1736123456789,
  "frame": { "width": 1280, "height": 720 },
  "tracks": [
    {
      "id": 17,
      "x": 640.5,
      "y": 430.2,
      "w": 120.0,
      "h": 280.0,
      "confidence": 0.78
    }
  ]
}
```

Server-derived fields:

```typescript
nx = x / frame.width;
ny = y / frame.height;
```

Use normalized thresholds, not hard-coded pixel constants.

## Sector model

Four sectors:

```text
far/mid-left       far/mid-right
near-left          near-right
```

Config:

```json
{
  "sectors": {
    "xSplit": 0.5,
    "nearY": 0.5,
    "activity": {
      "countWeight": 0.4,
      "movementWeight": 0.6,
      "emaAlpha": 0.1
    }
  }
}
```

Sector computation:

```typescript
function computeSector(nx: number, ny: number, cfg: SectorConfig): SectorName {
  const side = nx < cfg.xSplit ? 'left' : 'right';
  const depth = ny > cfg.nearY ? 'near' : 'midFar';
  return `${depth}${side === 'left' ? 'Left' : 'Right'}` as SectorName;
}
```

This absorbs the old contradiction between `y > 720` and `y > 540` by making the threshold normalized and tunable.

## Activity smoothing

Per sector:

```typescript
target = clamp(countWeight * countNorm + movementWeight * movementNorm, 0, 1)
activity = activity * (1 - emaAlpha) + target * emaAlpha
```

Movement should be normalized by frame diagonal or an empirically tuned max speed.

## CV output scheduling

- Update at 20–30 Hz.
- Use `linearRampToValueAtTime` or equivalent smoothing.
- No audio-rate CV writes.
- All physical output ranges come from `tunings.json`.
- Use `cvMap` presets from `04-eurorack-es9-swn.md`.

## Agent audio path

Agent performance mode is the main design. Use ES-9 inputs 1+2 as the primary rack/audio-return source, and ES-9 outputs 1/2 as the audible stereo main mix to the ES-9 1/4" balanced outs.

Software responsibilities:

- RMS/peak analysis.
- Spectral centroid or band-energy extraction for lights.
- Agent listening/responding to the rack return.
- Main-mix generation/processing/FX output to ES-9 outputs 1/2.
- Limiter, gain staging, watchdog, and feedback prevention.

Implementation cautions:

- Do not assume browser Web Audio can reliably address the ES-9's duplex multichannel I/O and DC-coupled CV channels; verify the actual runtime on the Mac mini.
- If Node/Web Audio channel routing is flaky, use a proven CoreAudio/PortAudio/Max/DAW bridge and keep the server as state/control logic.
- The hardware-direct Stereo Line Out 1U or ES-9 internal mixer route is a safety bypass, not the default artistic path.

## Light state protocol to ESP32

Use one naming convention: `channels.j1` and `channels.j2`, with `bri` 0–100.

```json
{
  "type": "lights",
  "seq": 1842,
  "channels": {
    "j1": { "r": 180, "g": 90, "b": 30, "bri": 75 },
    "j2": { "r": 30, "g": 60, "b": 180, "bri": 60 }
  }
}
```

Rules:

- `r`, `g`, `b`: integers 0–255.
- `bri`: integer 0–100.
- Server sends only when changed enough or at a low keepalive rate.
- ESP32 clamps all values.

## ESP32 → server messages

```json
{ "type": "hello", "deviceId": "esp32-lisbon-01", "fwVersion": "0.1.0", "ip": "192.168.8.42" }
{ "type": "pong", "seq": 1842 }
{ "type": "heartbeat", "uptimeMs": 1234500, "freeHeap": 200000, "rssi": -55 }
{ "type": "error", "message": "..." }
```

## State snapshot

`GET /api/state` should return room/system state, not visitor state.

```json
{
  "mode": "run",
  "morphState": "opening",
  "cvConnected": true,
  "espConnected": true,
  "es9": { "cvOutputReady": true, "audioInputReady": true, "mainOutputReady": true, "duplexReady": true },
  "tracks": { "active": 3, "lastFrameAgeMs": 40 },
  "sectors": {
    "nearLeft": { "count": 1, "activity": 0.62 },
    "nearRight": { "count": 0, "activity": 0.10 },
    "midFarLeft": { "count": 1, "activity": 0.35 },
    "midFarRight": { "count": 1, "activity": 0.44 }
  },
  "lights": {
    "j1": { "r": 180, "g": 90, "b": 30, "bri": 75 },
    "j2": { "r": 30, "g": 60, "b": 180, "bri": 60 }
  }
}
```

## Fault handling

- CV worker disconnect >5 s: decay sector activity to zero.
- ESP32 disconnect: keep server running; log and retry.
- ES-9 CV output failure: enter safe mode; stop morph; show alert in admin.
- ES-9 main audio output failure or agent audio crash: fade/kill software output, stop morph, switch to hardware bypass if needed.
- Audio listener/analyser failure: keep safe audio output if possible; lights fall back to sector-derived colors; alert admin.
- `/api/silence`: ramp CVs and main audio to zero and send lights black/low within 500 ms.
