#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

echo "== macOS audio devices =="
if command -v system_profiler >/dev/null 2>&1; then
  system_profiler SPAudioDataType | sed -n '/ES-9/,+10p;/Anker/,+6p' || true
else
  echo "system_profiler not available on this platform"
fi

echo
echo "== Python sounddevice inventory =="
python3 - <<'PY'
try:
    import sounddevice as sd
except Exception as exc:
    raise SystemExit(f"sounddevice unavailable: {exc}\nInstall with: python -m pip install -r requirements.txt")
for i, d in enumerate(sd.query_devices()):
    name = str(d.get('name', ''))
    if any(key.lower() in name.lower() for key in ('ES-9', 'Anker', 'BlackHole', 'MacBook', 'Studio Display', 'Microphone')):
        print(i, name, 'in=', d.get('max_input_channels'), 'out=', d.get('max_output_channels'), 'sr=', d.get('default_samplerate'))
print('default', sd.default.device)
PY

echo
echo "== Camera bridge endpoint check =="
CAMERA_URL="${LISBON_CAMERA_STATUS_URL:-http://127.0.0.1:8765/status}"
if command -v curl >/dev/null 2>&1 && curl -fsS --max-time 2 "$CAMERA_URL" >/tmp/lisbon-camera-status.json 2>/dev/null; then
  python3 -m json.tool /tmp/lisbon-camera-status.json || cat /tmp/lisbon-camera-status.json
else
  echo "camera bridge not responding at $CAMERA_URL (ok if it is not running yet)"
fi

echo
echo "== PlatformIO =="
if command -v pio >/dev/null 2>&1; then
  pio --version
else
  echo "PlatformIO CLI not found; install before uploading ESP32 firmware"
fi
