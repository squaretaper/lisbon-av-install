# ESP32 Firmware and Lighting

## Firmware role

Final-install ESP32 firmware can still become a networked LED endpoint. The active bench/install firmware right now is simpler and intentionally local: `firmware/dual_strip_dystopia_test/` runs FastLED red-only patterns and accepts one-character serial commands from the Mac over `/dev/cu.usbserial-0001` at `115200` baud.

Current serial responsibilities:

- Drive two WS2811 data outputs using FastLED.
- Stay pure red on every installed LED pixel: generated colors are always `CRGB(red, 0, 0)` or black.
- Accept mode, brightness, chase-speed, pulse-depth, and packet-span commands from the Mac soundscape sync bridge.
- Provide serial status with `?`.

Future networked endpoint responsibilities:

- Connect to travel-router WiFi.
- Connect to server `WS /ws/esp`.
- Receive `lights` frames.
- Drive two WS2811 data outputs.
- Expose heartbeat/error telemetry.
- Show connection state on GPIO27 status LED.

Non-responsibilities:

- No audio logic.
- No CV logic.
- No morph logic except displaying frames.
- No visitor/PWA identity logic.

## Pin map

| Function | ESP32 pin | Circuit |
|---|---:|---|
| J1 DATA | GPIO25 | ESP32 → AHCT125 1A → 1Y → R1 470 Ω → J1 DATA |
| J2 DATA | GPIO26 | ESP32 → AHCT125 2A → 2Y → R2 470 Ω → J2 DATA |
| Status LED | GPIO27 | GPIO → R3 220 Ω → red LED → GND |
| Logic 5 V | VIN/5V | USB-derived 5 V to AHCT125 VCC only |
| Ground | GND | common ground with LED PSU |

## Current serial soundscape sync

The live bridge is `lighting/lisbon_esp32_soundscape_sync.py`. It tails `audio/runtime/swn_camera_soundscape_status.json` and sends the existing one-character firmware protocol:

```text
0 = all red
1 = chasing red trains / frequency-chase mode
2 = glitch strobe / fault sparks
3 = running together
4 = low dystopian breath/scan
x = blackout
a = firmware auto mode
+ / - = brightness in 16-count steps
> / < = faster/slower chase speed in 4 ms steps
] / [ = deeper/shallower breathing pulse depth
} / { = wider/tighter packet span for cross-rhythm drone chases
? = status
```

Run against the connected ESP32:

```bash
. .venv/bin/activate
python \
  lighting/lisbon_esp32_soundscape_sync.py \
  --serial /dev/cu.usbserial-0001 \
  --status-path audio/runtime/swn_camera_soundscape_status.json \
  --interval 0.02 \
  --serial-delay 0.001 \
  --initial-mode 0 \
  --initial-brightness 64 \
  --initial-chase-ms 96 \
  --initial-pulse-depth 42 \
  --initial-packet-span 20 \
  --max-brightness-steps 6 \
  --max-param-steps 6
```

Set `--initial-mode` / `--initial-brightness` / `--initial-chase-ms` / `--initial-pulse-depth` / `--initial-packet-span` to the last known ESP32 serial status (`?`) before starting; the values above are safe reset/default values for the current low-latency drone-chase bridge.

Mapping policy:

- If ES-9 input 1/2 audio telemetry is nonzero, mode follows measured input frequency/transient/glitch features directly.
- Higher-frequency transient/glitch energy drives mode `2` as a pure-red strobe/fault effect at high brightness.
- Low-frequency drone energy drives mode `1` as the mostly-always-present chasing packet field; dominant drone frequency smoothly controls chase speed and packet span, so lower drones move slower with wider cross-rhythm/collision offsets, while higher drones tighten into faster smaller packets. Audio energy/low-band strength control breathing pulse depth and brightness.
- If ES-9 input 1/2 is silent, mode follows the live SWN CV/soundscape vector instead: Browse plus the CV7 movement-gate proxy drive frequency-chase; Dispersion/Pattern/Depth drive glitch mode.
- Person/camera features are only an idle fallback now; they should not dominate the lighting when soundscape frequency/glitch signals are available.
- Brightness is capped conservatively (`<= 176/255`) and moves in bounded serial `+`/`-` steps; current live bridge uses larger bounded steps (`--max-brightness-steps 6 --max-param-steps 6`) at `50 Hz` (`--interval 0.02`) so speed/pulse/span keep up with the analyzed drone without feeling laggy. Each transition log appends `age=...ms`, measured from the audio status JSON timestamp to the serial decision, for quick latency/correlation checks.

## Future JSON light protocol

The network/WebSocket protocol below is not the active bench path; current live control uses the serial bridge above. If/when JSON frames are revived for the final install, keep the Lisbon red-only look unless the installation direction explicitly changes.

Server sends:

```json
{
  "type": "lights",
  "seq": 1842,
  "channels": {
    "j1": { "r": 180, "g": 0, "b": 0, "bri": 75 },
    "j2": { "r": 90, "g": 0, "b": 0, "bri": 60 }
  }
}
```

ESP32 clamps:

- RGB: 0–255.
- `bri`: 0–100.

Suggested final channel output:

```text
out = rgb_channel * (bri / 100.0) * globalBrightnessLimit
```

`globalBrightnessLimit` should default conservatively until current draw is measured.

## Connection states

GPIO27 status LED:

- Fast blink: WiFi connecting.
- Slow blink: WiFi connected, WebSocket connecting.
- Solid or heartbeat pulse: WebSocket connected and frames recently received.
- Double blink: server timeout / reconnect loop.

## Boot verification

On boot after WebSocket connection:

1. Send a short low-brightness red pulse on J1 only.
2. Send a short low-brightness red pulse on J2 only.
3. Return to black/idle.

Use this to verify channel order and connector mapping without blasting the room. During the current Lisbon look, avoid blue/green/white boot accents on installed strips.

## Safety behavior

- If no valid frame for >2 seconds: hold last frame or decay to idle, configurable.
- If no valid frame for >10 seconds: fade to black/low idle.
- On malformed JSON: ignore and report error.
- On repeated WebSocket failure: keep reconnecting; do not reboot-loop unless heap/network stack is wedged.

## Electrical assumptions

- ESP32 powered by USB-C only.
- AHCT125 powered by ESP32 VIN/USB-derived 5 V.
- LED strips powered by the 12 V PSU.
- Grounds common.
- No external 5 V injection into ESP32 VIN.

## Color-order verification

WS2811 strips may be RGB, GRB, BRG, etc. Keep color order in firmware config and verify with boot routine before show.

## Current limiting

Start with conservative limits:

```text
globalBrightnessLimit = 0.20
maxBri = 50
```

Raise only after measuring current, checking wire/connector heat, and verifying PSU/fuse margin.
