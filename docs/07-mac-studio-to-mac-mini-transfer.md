# Mac Studio Prototype → Mac mini Transfer

## Principle

The Mac mini should not be a fresh science project in Lisbon. The Mac Studio build must become a reproducible repo/config that can be cloned and verified on the Mac mini before travel/install.

## What must be reproducible

- Node version and package lock.
- Python version/venv and requirements lock.
- CV model weights location.
- ES-9 device names and channel map.
- Camera device selection and resolution.
- Travel-router network config.
- ESP32 firmware build and secrets/example config.
- `tunings.json`, `states.json`, `cvMap`, sector thresholds.
- Startup command/launch wrapper.

## Suggested repo layout

```text
/firmware/
/server/
/cv/
/config/
  mac-studio.local.json
  mac-mini-lisbon.local.json
  tunings.json
  states.json
/docs/
/scripts/
  bootstrap-macos.sh
  run-dev.sh
  run-install.sh
  check-devices.sh
```

Keep secrets out of git. Commit `*.example` files.

## Mac Studio completion checklist

- Day 1 gates pass on Studio.
- Full dry run passes on Studio.
- ESP32 connects to server over travel-router WiFi.
- ES-9 physical CV output mapping documented.
- ES-9 input mapping documented.
- Camera works in dim room.
- Rack patch photographed.
- `tunings.json` and `states.json` saved.
- Startup command is one script, not a memory ritual.

## Transfer checklist

On Mac mini:

1. Install system dependencies.
2. Clone repo.
3. Install Node dependencies.
4. Create Python venv and install CV dependencies.
5. Copy model weights or download explicitly.
6. Copy local config from example.
7. Connect ES-9 and camera.
8. Run `scripts/check-devices.sh`.
9. Run Day 1 gates again.
10. Run full system with ESP32 and rack.

## Device remapping

Do not assume audio/camera device names match between Studio and Mac mini. The install config should support explicit device selection.

Record:

- ES-9 input device name.
- ES-9 output device name.
- Camera device name/resolution/FPS.
- Network interface/IP.
- ESP32 static/reserved IP if used.

## Launch behavior

For the install, prefer one command:

```bash
./scripts/run-install.sh
```

That command should start:

- Node server.
- CV worker.
- logging/telemetry.

It should not require a development terminal dance.

## Offline requirement

The show should run without internet once dependencies/model weights are installed. Travel router provides local network; cloud services are out of scope.
