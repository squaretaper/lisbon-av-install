# Lisbon Install Runbook

## Arrival inventory

Confirm in person:

- Mac mini arrived with artist.
- LED strips are on site.
- Mixer/Genelecs are on site.
- Palette 62/rack survived travel.
- ESP32 enclosure survived travel.
- Camera/tripod/router/cables/tools are present.
- EU power adapters and safe mains cables are present.

## Physical setup order

1. Place rack, mixer, monitors, Mac mini, router, ESP32 enclosure.
2. Inspect rack modules and patch cables.
3. Recreate/verify rack patch from photos.
4. Set up travel router and local WiFi.
5. Mount camera/tripod at install end.
6. Route LED strips and power wiring safely.
7. Keep LED strips disconnected until controller power checks pass.

## Power checks before load

1. Check ESP32 enclosure visually.
2. With no power, verify no obvious shorts on LED outputs.
3. Power ESP32 by USB; confirm status LED boot/reconnect behavior.
4. Power 12 V rail with no strips; confirm power-good LED and no heat.
5. Confirm protected 12 V rail is not feeding ESP32 VIN.
6. Connect one strip/channel at low brightness.
7. Connect second strip/channel at low brightness.

## Software startup

On Mac mini:

```bash
cd /path/to/lisbon-av-install
./scripts/run-install.sh
```

Then verify:

- `GET /health` OK.
- `/api/state` shows server running.
- CV worker connected.
- ESP32 connected.
- ES-9 CV output, audio input, and main output ready.
- Admin dashboard or logs show sector activity.

## Rack/audio startup

1. Rack, mixer, and agent main output down/muted.
2. Power rack.
3. Confirm SWN state/pitches.
4. Confirm VCA/CV patch and SWN/audio return into ES-9 inputs 1+2.
5. Confirm Mac/agent sends low-level stereo main mix to ES-9 outputs 1/2 / 1/4" main outs.
6. Bring mixer/monitors up slowly.
7. Trigger or walk sectors; confirm voice amplitudes respond and agent output changes musically.
8. Confirm ES-9 listener/analyser sees audio and lights react.
9. Confirm hardware bypass path is available but muted/unselected unless needed.

## Calibration

### Camera/sectors

- Set frame resolution/FPS.
- Walk near-left, near-right, mid/far-left, mid/far-right.
- Tune `xSplit` and `nearY` in normalized coordinates.
- Confirm no dead zones at common visitor paths.

### CV/rack

- Tune VCA max voltage.
- Tune bed level.
- Tune browse/modulation scale.
- Confirm empty room is intentional: low bed or silence.

### Lights

- Verify J1/J2 mapping.
- Verify color order.
- Set conservative global brightness.
- Raise only after current/heat check.

### Morph PWA if used

- Program NFC tag to local URL.
- Verify QR fallback.
- Press button three times; confirm morph schedule.
- Confirm `/api/silence` remains available.

## Show operation

Before visitors:

- Start system.
- Confirm state snapshot.
- Confirm rack audio reaches the Mac/agent and the ES-9 main outs.
- Confirm LED output.
- Confirm camera tracking.
- Keep logs visible or tailable.

During show:

- Do not edit live code.
- Use `/api/silence` if audio/lighting goes unsafe.
- If agent audio path fails or feeds back, hit `/api/silence`, mute mixer/channel, and switch to documented hardware bypass only after levels are safe.
- If CV fails, allow sectors to decay; restart CV worker when safe.
- If ESP32 fails, sound can continue; restart controller/server link.

## Shutdown

1. Trigger silence/fade for CV, lights, and agent main output.
2. Stop server/CV worker.
3. Turn monitor/mixer down.
4. Power rack down.
5. Power LED PSU/enclosure down.
6. Shut down Mac mini.
7. Photograph final patch/state if changed.
