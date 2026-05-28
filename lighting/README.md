# ESP32 lighting sync bridge

`lisbon_esp32_soundscape_sync.py` tails the soundscape status JSON produced by `audio/lisbon_swn_camera_bridge.py` and converts it into bounded one-character serial commands for the ESP32 red-light firmware.

Priority order:

1. Measured ES-9 stereo input telemetry when present.
2. Generated SWN/CV vector as a musical proxy when ES-9 input is silent.
3. Camera/person scene only as an idle fallback.

The bridge does not send color values. It selects firmware red-only motion modes and adjusts brightness, chase speed, pulse depth, and packet span using compact relative commands.

## Dry run

```bash
python lighting/lisbon_esp32_soundscape_sync.py \
  --dry-run \
  --status-path audio/runtime/swn_camera_soundscape_status.json \
  --interval 0.02
```

## Live serial run

```bash
python lighting/lisbon_esp32_soundscape_sync.py \
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

Before a live run, send `?` in a serial monitor if needed and seed the `--initial-*` arguments with the controller's actual current state. That avoids command-spam while the host-side shadow state catches up.
