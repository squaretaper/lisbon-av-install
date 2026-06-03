#!/usr/bin/env bash
# Launcher for the deterministic reflective reviewer.
#
# Defaults: 2-minute window, gentle mutation, 10-minute TTL.
# Invoked from cron or manually:
#
#   audio/run_reflective_reviewer.sh decide
#   audio/run_reflective_reviewer.sh agent-brief
#
# The reviewer never touches hardware; it reads telemetry JSON and writes
# advisory profile JSON. The bridge clamps everything on read.

set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_DIR"

PYTHON="${PYTHON:-python3}"
COMMAND="${1:-decide}"
shift || true

case "$COMMAND" in
  decide)
    exec "$PYTHON" -m audio.reflective_reviewer decide \
      --window-seconds "${WINDOW_SECONDS:-120}" \
      --jitter "${JITTER:-0.08}" \
      --ttl-seconds "${TTL_SECONDS:-600}" \
      --score-window \
      "$@"
    ;;
  agent-brief)
    exec "$PYTHON" -m audio.reflective_reviewer agent-brief \
      --window-seconds "${WINDOW_SECONDS:-90}" \
      "$@"
    ;;
  apply-profile)
    exec "$PYTHON" -m audio.reflective_reviewer apply-profile "$@"
    ;;
  score)
    exec "$PYTHON" -m audio.profile_scorer \
      --window-seconds "${WINDOW_SECONDS:-120}" \
      "$@"
    ;;
  *)
    echo "usage: $0 {decide|agent-brief|apply-profile|score} [args...]" >&2
    exit 2
    ;;
esac
