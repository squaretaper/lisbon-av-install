# ESP32 firmware

Firmware sketches for the Lisbon lighting controller. All sketches target an ESP32 dev board through PlatformIO/Arduino.

## Active install firmware

`dual_strip_dystopia_test/` is the active red-only dual-strip firmware.

Hardware assumptions:

- J1 data: ESP32 GPIO25 -> SN74AHCT125 buffer -> 470 ohm series resistor -> WS2811 data.
- J2 data: ESP32 GPIO26 -> SN74AHCT125 buffer -> 470 ohm series resistor -> WS2811 data.
- Status LED: GPIO27 through 220 ohm resistor to ground.
- Case light-pipe indicators: GPIO13, GPIO14, GPIO32, GPIO33, bottom-to-top.
- WS2811 strip color order for the bench-proven strip is `BRG`.
- Strip pixels are intentionally pure red/black only.

Build/upload:

```bash
cd firmware/dual_strip_dystopia_test
pio run
pio run -t upload
pio device monitor -b 115200
```

Serial protocol:

| Command | Meaning |
|---|---|
| `0` | all red / low breathing channel check |
| `1` | red chasing packets / frequency chase |
| `2` | glitch strobe / fault cells |
| `3` | running together |
| `4` | dystopian breath/scan |
| `x` | blackout |
| `a` | firmware auto mode |
| `+` / `-` | brightness up/down |
| `>` / `<` | chase speed faster/slower |
| `]` / `[` | breathing pulse depth up/down |
| `}` / `{` | packet span wider/tighter |
| `?` | print current mode/parameters |

## Bench sketches

- `status_led_test/` — GPIO27 heartbeat/status LED smoke test.
- `j1_strip_test/` — single-channel strip sanity check.
- `j1_red_chaos_test/` — older J1 animation exploration.
- `light_pipe_led_test/` — case light-pipe GPIO order validation.

Generated `.pio/` build directories are excluded from git.
