#!/usr/bin/env bash
# Launcher for the ESP32 soundscape sync.
# Reads audio/runtime/swn_camera_soundscape_status.json and drives the
# dual-strip dystopia firmware via /dev/cu.usbserial-0001.
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_DIR"

if [ ! -d .venv ]; then
  /usr/bin/python3 -m venv .venv
fi
. .venv/bin/activate
python -m pip install -q -r requirements.txt

exec python -m lighting.lisbon_esp32_soundscape_sync \
  --status-path "${LISBON_STATUS_PATH:-$REPO_DIR/audio/runtime/swn_camera_soundscape_status.json}" \
  --serial "${LISBON_ESP32_SERIAL:-/dev/cu.usbserial-0001}" \
  --baud "${LISBON_ESP32_BAUD:-115200}" \
  --interval "${LISBON_ESP32_INTERVAL:-0.02}" \
  --duration "${LISBON_ESP32_DURATION:-0}" \
  --initial-packet-span "${LISBON_ESP32_PACKET_SPAN:-20}" \
  --max-brightness-steps "${LISBON_ESP32_BRIGHT_STEPS:-6}" \
  --max-param-steps "${LISBON_ESP32_PARAM_STEPS:-6}" \
  --serial-delay "${LISBON_ESP32_SERIAL_DELAY:-0.001}"
