#!/usr/bin/env bash
# Idempotent installer for all Lisbon persistent services.
#
# Loads (or reloads) every LaunchAgent under scripts/launchagents into the
# current user's GUI session. Safe to run repeatedly. Will not stomp existing
# user-edited copies in ~/Library/LaunchAgents unless --overwrite is passed.
#
# Usage:
#   scripts/install-launchagents.sh           # link + load missing
#   scripts/install-launchagents.sh --overwrite  # overwrite + reload all
#   scripts/install-launchagents.sh --status  # just print current state
#   scripts/install-launchagents.sh --uninstall  # bootout + unlink
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SRC_DIR="$REPO_DIR/scripts/launchagents"
DST_DIR="$HOME/Library/LaunchAgents"
LOG_DIR="$HOME/Library/Logs"
GUI_DOMAIN="gui/$(id -u)"

mkdir -p "$DST_DIR" "$LOG_DIR"

action="${1:-install}"

agents=(
  "ai.ganchitecture.lisbon-camera-probe"
  "ai.ganchitecture.lisbon-audio-probe"
  "ai.ganchitecture.lisbon-swn-bridge"
  "ai.ganchitecture.lisbon-esp32-sync"
  "ai.ganchitecture.lisbon-reflective-reviewer"
)

print_status() {
  echo "=== Status ==="
  for label in "${agents[@]}"; do
    if launchctl print "$GUI_DOMAIN/$label" >/dev/null 2>&1; then
      pid=$(launchctl print "$GUI_DOMAIN/$label" | awk '/^[[:space:]]*pid =/{print $3; exit}')
      state=$(launchctl print "$GUI_DOMAIN/$label" | awk '/^[[:space:]]*state =/{print $3; exit}')
      printf "  %-55s state=%s pid=%s\n" "$label" "${state:-?}" "${pid:-none}"
    else
      printf "  %-55s NOT LOADED\n" "$label"
    fi
  done
}

install_agent() {
  local label="$1"
  local overwrite="$2"
  local src="$SRC_DIR/$label.plist"
  local dst="$DST_DIR/$label.plist"
  if [ ! -f "$src" ]; then
    echo "  ! missing source: $src" >&2
    return 1
  fi
  if [ -f "$dst" ] && [ "$overwrite" != "1" ]; then
    if ! diff -q "$src" "$dst" >/dev/null 2>&1; then
      echo "  ! $dst already exists and differs from repo. Re-run with --overwrite to replace."
      return 0
    fi
  fi
  cp "$src" "$dst"
  launchctl bootout "$GUI_DOMAIN/$label" 2>/dev/null || true
  launchctl bootstrap "$GUI_DOMAIN" "$dst"
  launchctl enable "$GUI_DOMAIN/$label"
  launchctl kickstart -k "$GUI_DOMAIN/$label" 2>/dev/null || true
  echo "  + $label installed and started"
}

uninstall_agent() {
  local label="$1"
  local dst="$DST_DIR/$label.plist"
  launchctl bootout "$GUI_DOMAIN/$label" 2>/dev/null || true
  rm -f "$dst"
  echo "  - $label removed"
}

case "$action" in
  --status|status)
    print_status
    ;;
  --uninstall|uninstall)
    for label in "${agents[@]}"; do
      uninstall_agent "$label"
    done
    ;;
  --overwrite|overwrite)
    for label in "${agents[@]}"; do
      install_agent "$label" 1
    done
    echo
    print_status
    ;;
  install|--install|"")
    for label in "${agents[@]}"; do
      install_agent "$label" 0
    done
    echo
    print_status
    ;;
  *)
    echo "usage: $0 [install|--overwrite|--status|--uninstall]" >&2
    exit 2
    ;;
esac
