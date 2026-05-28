#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
APP_DIR="$ROOT/cv/camera_probe/LisbonCameraProbe.app"
OUT="$APP_DIR/Contents/MacOS/LisbonCameraProbe"

mkdir -p "$APP_DIR/Contents/MacOS"

swiftc \
  -framework AVFoundation \
  -framework CoreImage \
  -framework CoreGraphics \
  -framework ImageIO \
  -framework Network \
  -framework UniformTypeIdentifiers \
  "$ROOT/cv/camera_probe/main.swift" \
  -o "$OUT"

codesign --force --deep --sign - "$APP_DIR"
echo "Built and ad-hoc signed $APP_DIR"
