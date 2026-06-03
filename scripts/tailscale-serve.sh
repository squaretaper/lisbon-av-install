#!/usr/bin/env bash
# Set up Tailscale serve to expose the Lisbon AV bridges over HTTPS,
# tailnet-only (not public). Idempotent: resets the existing serve config
# and rebuilds.
#
# Adds:
#   /camera/   ->  http://127.0.0.1:8765/   (camera probe; live frame, MJPEG, status)
#
# Routes are added under /camera/ rather than at root so we can add more
# bridges later (/swn/, /hermes/) without colliding.
#
# Requirements:
#   - Tailscale.app installed and signed in
#   - Camera probe LaunchAgent running (scripts/install-launchagents.sh)
#   - Tailscale HTTPS feature enabled in admin console (it is by default)
set -euo pipefail

TS=/Applications/Tailscale.app/Contents/MacOS/Tailscale
if [ ! -x "$TS" ]; then
  echo "Tailscale.app not found at $TS" >&2
  exit 1
fi

action="${1:-up}"

case "$action" in
  up|install|"")
    echo "=== resetting existing serve config ==="
    "$TS" serve reset 2>&1 || true
    echo
    echo "=== adding /camera/ -> 127.0.0.1:8765 ==="
    "$TS" serve --bg --https=443 --set-path=/camera/ http://127.0.0.1:8765/
    echo
    "$TS" serve status
    ;;
  down|off|uninstall)
    echo "=== tearing down serve config ==="
    "$TS" serve reset 2>&1 || true
    "$TS" serve --https=443 off 2>&1 || true
    echo "Done."
    ;;
  status)
    "$TS" serve status
    ;;
  *)
    echo "usage: $0 [up|down|status]" >&2
    exit 2
    ;;
esac
