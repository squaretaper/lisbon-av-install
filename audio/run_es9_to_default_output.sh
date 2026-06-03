#!/usr/bin/env bash
# Backup audio path for the Lisbon install: ES-9 inputs 1/2 -> iLoud over BT.
# Only meaningful when the analog cable run from ES-9 to monitors is missing.
#
# WARNING: BT adds 100-300ms latency. Reactive material will feel late
# against the lights. Drone/ambient material will feel fine.
#
# Conflicts with the SWN bridge LaunchAgent on ES-9. Stop the bridge first:
#   launchctl bootout gui/$(id -u)/ai.ganchitecture.lisbon-swn-bridge
# Re-load with scripts/install-launchagents.sh when done.

set -euo pipefail
REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_DIR"

if [ ! -d .venv ]; then
  /usr/bin/python3 -m venv .venv
  .venv/bin/python -m pip install -q -r requirements.txt
fi

exec .venv/bin/python -m audio.es9_to_default_output \
  --input-device "${LISBON_BT_INPUT_DEVICE:-ES-9}" \
  --output-device "${LISBON_BT_OUTPUT_DEVICE:-iLoud}" \
  --input-channels "${LISBON_BT_LEFT:-1}" "${LISBON_BT_RIGHT:-2}" \
  --samplerate "${LISBON_BT_SR:-48000}" \
  --blocksize "${LISBON_BT_BLOCK:-256}" \
  --gain "${LISBON_BT_GAIN:-0.6}" \
  "$@"
