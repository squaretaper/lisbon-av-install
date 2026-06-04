#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
if [ ! -d .venv ]; then
  python3 -m venv .venv
fi
. .venv/bin/activate
python -m pip install -q -r requirements.txt
mkdir -p audio/runtime
exec python audio/lisbon_swn_camera_bridge.py \
  --camera-url "${LISBON_CAMERA_URL:-http://127.0.0.1:8765/frame.jpg}" \
  --device "${LISBON_AUDIO_DEVICE:-ES-9}" \
  --main-gain "${LISBON_MAIN_GAIN:-0.35}" \
  --input-left-channel "${LISBON_INPUT_LEFT_CHANNEL:-1}" \
  --input-right-channel "${LISBON_INPUT_RIGHT_CHANNEL:-2}" \
  --max-cv "${LISBON_MAX_CV:-0.18}" \
  --vision-mode "${LISBON_VISION_MODE:-people}" \
  --camera-hz "${LISBON_CAMERA_HZ:-5}" \
  --status-hz "${LISBON_STATUS_HZ:-60}" \
  --blocksize "${LISBON_BLOCKSIZE:-128}" \
  --stillness-deadband "${LISBON_STILLNESS_DEADBAND:-0.03}" \
  --stillness-frame-motion "${LISBON_STILLNESS_FRAME_MOTION:-0.03}" \
  --preview-hz "${LISBON_PREVIEW_HZ:-10}" \
  --yolo-model "${LISBON_YOLO_MODEL:-yolo11n.pt}" \
  --yolo-tracker "${LISBON_YOLO_TRACKER:-audio/trackers/lisbon_sticky_bytetrack.yaml}" \
  --tracker-max-missing "${LISBON_TRACKER_MAX_MISSING:-40}" \
  --status-path "${LISBON_STATUS_PATH:-audio/runtime/swn_camera_soundscape_status.json}" \
  --preview-path "${LISBON_PREVIEW_PATH:-audio/runtime/swn_camera_people_preview.jpg}"
