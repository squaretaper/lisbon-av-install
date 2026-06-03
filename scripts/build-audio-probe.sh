#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
APP_DIR="$ROOT/audio/audio_probe/LisbonAudioProbe.app"
OUT="$APP_DIR/Contents/MacOS/LisbonAudioProbe"
INFO="$APP_DIR/Contents/Info.plist"

mkdir -p "$APP_DIR/Contents/MacOS"

# Info.plist — establishes the bundle identity that TCC binds to.
# NSMicrophoneUsageDescription is required for AVFoundation audio capture
# under the user's TCC grant.
cat > "$INFO" <<'PLIST'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>CFBundleIdentifier</key>
  <string>ai.ren.lisbon.audio-probe</string>
  <key>CFBundleName</key>
  <string>Lisbon Audio Probe</string>
  <key>CFBundleExecutable</key>
  <string>LisbonAudioProbe</string>
  <key>CFBundlePackageType</key>
  <string>APPL</string>
  <key>CFBundleShortVersionString</key>
  <string>1.0</string>
  <key>CFBundleVersion</key>
  <string>1</string>
  <key>LSUIElement</key>
  <true/>
  <key>NSMicrophoneUsageDescription</key>
  <string>Lisbon AV install captures audio from the Anker C200 microphone for slow-loop room analysis. The reflective reviewer reads RMS and band ratios to score whether the room is too quiet, too busy, or balanced. No audio is sent off-machine.</string>
</dict>
</plist>
PLIST

swiftc \
  -O \
  -framework AVFoundation \
  -framework CoreMedia \
  -framework Accelerate \
  -framework Network \
  -framework UniformTypeIdentifiers \
  "$ROOT/audio/audio_probe/main.swift" \
  -o "$OUT"

codesign --force --deep --sign - "$APP_DIR"
echo "Built and ad-hoc signed $APP_DIR"
