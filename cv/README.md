# Lisbon Camera Bridge

Native macOS AVFoundation bridge for the Lisbon AV computer-vision pipeline.

The target deployment is a signed-in Mac GUI session, not a headless daemon. macOS Camera/TCC permissions are tied to the GUI app identity, so the bridge is packaged as a small LSUIElement app:

`cv/camera_probe/LisbonCameraProbe.app`

The bundle name is "Lisbon Camera Bridge" and the default bundle identifier is:

`ai.ren.lisbon.camera-probe`

If you change the bundle identifier or rebuild/sign identity after granting Camera permission, macOS may ask for permission again.

## Live endpoints

Default port: `8765`

- `GET /health` — process/server health.
- `GET /status` — current frame metadata and freshness.
- `GET /frame.jpg` — latest JPEG frame.
- `GET /stream.mjpeg` — multipart MJPEG stream for live viewers/agents.
- `GET /` — minimal browser viewer.

The bridge also writes the latest frame to:

`cv/captures/latest.jpg`

That file path is useful for local vision tools that consume images from disk.

## Build

```bash
scripts/build-camera-bridge.sh
```

## Run on the signed-in GUI session

From this repo, direct foreground run:

```bash
cv/camera_probe/LisbonCameraProbe.app/Contents/MacOS/LisbonCameraProbe \
  --port 8765 \
  --snapshot-path cv/captures/latest.jpg \
  --snapshot-interval 0.5 \
  --fps 10
```

If launching from a background shell but the camera permission belongs to the active desktop user, run through that GUI user's launch context:

```bash
GUI_USER=$(stat -f '%Su' /dev/console)
GUI_UID=$(stat -f '%u' /dev/console)
sudo launchctl asuser "$GUI_UID" sudo -u "$GUI_USER" /usr/bin/open -n \
  cv/camera_probe/LisbonCameraProbe.app --args \
  --port 8765 \
  --snapshot-path "$PWD/cv/captures/latest.jpg" \
  --snapshot-interval 0.5 \
  --fps 10
```

## Verify live camera

```bash
curl -s http://127.0.0.1:8765/status | python3 -m json.tool
curl -fsS http://127.0.0.1:8765/frame.jpg -o /tmp/lisbon-live-frame-test.jpg
```

Browser viewer:

`http://127.0.0.1:8765/`

## Mock-mode test

Mock mode avoids Camera permission and generates synthetic JPEG frames:

```bash
scripts/build-camera-bridge.sh
python3 cv/tests/test_camera_bridge_mock_http.py
```

This checks `/status`, `/frame.jpg`, `/stream.mjpeg`, and snapshot writing.
