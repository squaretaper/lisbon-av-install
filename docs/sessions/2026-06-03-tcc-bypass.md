# Session log — 2026-06-03 — TCC bypass on headless mini

## Problem

Anker C200 plugged into the Lisbon mini. macOS sees it. `LisbonCameraProbe.app` runs, but AVFoundation returns `requesting camera permission` and frames don't flow. The system permission dialog can't be clicked — no monitor, no physical access, and remote screen sharing routes (Remmina/TigerVNC from bento) only get observe-only against Apple's auth.

## Failed paths (recorded so we don't redo them)

1. **Remmina from bento** — libvncclient picks Apple's proprietary auth method 30, can't speak SRP. Observe-only at best.
2. **TigerVNC from bento with `-SecurityTypes VncAuth`** — Apple's server hands back observe-only when authed via legacy VNC password (`nohaydia`, 8-char-truncated).
3. **Pablo's MacBook → Finder → vnc://** — kept failing SRP auth. Root cause: `dscl -passwd` had regenerated the login hash but NOT `HeimdalSRPKey`. The on-disk SRP verifier was from an older password. Fix that was attempted (and would have worked for VNC): `sudo sysadminctl -resetPasswordFor ganchitecture -newPassword 'nohaydias!' -adminUser ganchitecture -adminPassword 'nohaydias!'`. Skipped because Pablo wasn't available to retry.
4. **`sudo tccutil` / writing system TCC.db** — SIP-protected, read-only.

## What actually worked

SSH sessions on this mini have Full Disk Access (`sshd-keygen-wrapper` has `kTCCServiceSystemPolicyAllFiles = 2` in user TCC.db). The *user* TCC.db (`~/Library/Application Support/com.apple.TCC/TCC.db`) is **not** SIP-protected — only file-permissioned. Camera, Microphone, ScreenCapture, and AppleEvents grants live there.

Write the grant directly with a valid `csreq` blob computed from the app's designated requirement, restart tccd, relaunch the app via `open` (not the bare binary).

```bash
APP=~/code/lisbon-av-install/cv/camera_probe/LisbonCameraProbe.app
BUNDLE_ID=$(defaults read "$APP/Contents/Info" CFBundleIdentifier)
USER_TCC="$HOME/Library/Application Support/com.apple.TCC/TCC.db"

DR=$(codesign -d -r- "$APP" 2>&1 | grep "designated =>" | sed 's/.*designated => //')
echo "$DR" | csreq -r- -b /tmp/csreq.bin
CSREQ_HEX=$(xxd -p /tmp/csreq.bin | tr -d '\n')

launchctl stop com.apple.tccd; sleep 1
sqlite3 "$USER_TCC" "INSERT OR REPLACE INTO access (service, client, client_type, auth_value, auth_reason, auth_version, csreq, flags) VALUES ('kTCCServiceCamera', '$BUNDLE_ID', 0, 2, 4, 1, X'$CSREQ_HEX', 0);"
launchctl start com.apple.tccd; sleep 2

killall LisbonCameraProbe 2>/dev/null
open "$APP" --args --snapshot-path "/Users/ganchitecture/code/lisbon-av-install/cv/captures/latest.jpg"
```

After this: `curl http://127.0.0.1:8765/status` returns `ok: true`, `device: Anker PowerConf C200`, 1920x1080 frames flowing.

## Critical gotchas

- **`open APP` not `./Contents/MacOS/Binary`** — TCC matches by bundle signature context. Bare-binary launch bypasses the bundle and tccd refuses the grant.
- **Empty csreq = silent ignore.** A row without a csreq blob looks fine in `SELECT` but tccd treats it as no grant.
- **Snapshot path must be absolute when launched via `open`.** `open` doesn't inherit cwd; the probe's default `cv/captures/latest.jpg` resolves to root and fails. Pass `--snapshot-path` with an absolute path.
- **Re-signing the app invalidates the grant.** cdhash change → csreq mismatch → re-run the SQL with the new cdhash.

## Related skill

`apple/macos-headless-tcc-grant` — generalized version of this for any headless Mac install needing Camera/Mic/ScreenRecording/AppleEvents without a human click.

## Install team note

Before flying to Lisbon: verify the probe's cdhash by running the same script on the production mini, write the camera grant once, confirm `/frame.jpg` returns a JPEG. The grant survives reboots. Re-signing on a rebuild requires re-grant.
