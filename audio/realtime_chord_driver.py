#!/usr/bin/env python3
"""Realtime chord driver for the Lisbon SWN install.

Architecture: two-loop heuristic.

  slow loop  reflective_reviewer.py
             scores last N seconds of scene, picks a family,
             writes the full heuristic_profile.json every minute or so.
             Owns lights, audio bias, cv knobs, BASE chord.

  fast loop  realtime_chord_driver.py   <-- this file
             reads bridge's swn_camera_soundscape_status.json,
             computes density from person_scene,
             reads current heuristic_profile.json as BASE,
             emits a modulated chord block based on the room RIGHT NOW.
             Owns ONLY chord block. Preserves everything else verbatim.

The bridge's profile poller (lisbon_swn_camera_bridge.py:poll_profile_loop)
runs at 1 Hz reading by mtime. We write at ~1.3 Hz to guarantee the bridge
sees a fresh file every poll.

No bridge restart needed. Set-and-forget; Ctrl-C to stop.
"""
from __future__ import annotations

import argparse
import json
import os
import signal
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

# --- Density → harmony policy --------------------------------------------------
#
# Density is a 0..1 signal combining headcount and activity. It maps to:
#
#  voicing band (with hysteresis to avoid voicing thrash at band edges):
#       0.00 - 0.18    drone           (single sustained voice cluster)
#       0.18 - 0.45    open_fifth      (austere, room is sparse)
#       0.45 - 0.72    suspended_fourth (chord opens up but unresolved)
#       0.72 - 1.00    major_triad     (full, bright, busy room)
#
#  root_semitones: 36 (D2) at density 0, lifts to 48 (D3) at density 1.
#       12 semitones of room-driven transpose. The bridge's CV5 still
#       handles fine bipolar transpose at the patch layer; this is the
#       structural pitch motion.
#
#  pitch_wander_scale: 0.20 (still empty room → glacial) → 1.00 (busy →
#       full chord_palette wander). The bridge applies this multiplier to
#       its centroid/motion driven pitch wobble.
#
#  smoothing_hz: 0.40 (slow, deep_fifth-style) → 1.20 (snappier as density
#       climbs). This controls how fast the chord_palette transitions.
#
# All values clamp to the chord_palette validation ranges.

VOICING_BANDS = [
    # (low, high, voicing) — list order = ascending density.
    # Bands overlap by HYST so a hovering density doesn't thrash.
    # Names must match audio/chord_palette.py VOICINGS keys.
    #
    # Operator 6/4 r5: "more requiem style dirge minor key vibes."
    # Home is minor_triad. Empty/floor uses deep_fifth (sub + fifth, no
    # third, mournful and unresolved). Mid-density opens to minor_triad
    # proper. High density layers in quartal (modal, hollow). Peak active
    # room dips into cluster_tight for the dissonance Pablo said is OK.
    # No major_triad anywhere — the room never resolves bright.
    # 6/4 r5b: floor band uses minor_triad (was deep_fifth). deep_fifth's
    # sub-octave voice (-12 st offset) at root 34 (Bb1) pushed voice 1 to
    # CV ~= -0.10V which the bridge clamps to 0 — making voice 1 silent.
    # minor_triad keeps the dirge minor home but lands voice 1 ON the
    # root so all three voices are audible at the floor.
    (0.00, 0.18, "minor_triad"),      # empty: minor home, all voices audible
    (0.18, 0.45, "minor_triad"),      # sparse: same voicing, root climbs
    (0.45, 0.72, "quartal"),          # building: hollow fourths, modal tension
    (0.72, 1.00, "cluster_tight"),    # peak: minor 2nd cluster, controlled dissonance
]
VOICING_HYSTERESIS = 0.05  # density delta required to leave a band

ROOT_SEMITONES_MIN = 36.0  # D2 — solid dirge floor
ROOT_SEMITONES_MAX = 46.0  # A#2 — never climbs out of mourning band

WANDER_MIN = 0.05  # 6/4 r6: dropped 0.15 → 0.05 — calm room is near-static drone
WANDER_MAX = 0.55  # was 0.70 — even peak stays slow

SMOOTHING_MIN = 0.20  # 6/4 r6: slower chord crossfades at low density (more drone)
SMOOTHING_MAX = 0.65  # was 0.80 — peak still doesn't snap

# Density input EMA — soaks YOLO bbox jitter so the chord doesn't flicker.
DENSITY_EMA_HZ = 0.5  # ~320 ms tau

# 6/5 r5: room-silence EMA. Slow timescale (~60s tau) on room RMS from
# the LisbonAudioProbe. Used to multiply pitch_wander_scale: quiet room
# narrows the chord drift (piece settles inward), audibly active room
# widens it (piece becomes more restless in response to restlessness).
# This is the metaphysical move — the architecture stops keeping time
# when there is no one to keep it for.
ROOM_LOUDNESS_EMA_HZ = 1.0 / 60.0  # ~60s tau, slow as ceremony
# Loudness mapping: RMS in [0, 1] linear scale from the probe. A quiet
# gallery sits around 0.02-0.05; a busy room with talking sits at 0.1-0.3.
# We map to a wander multiplier in [SILENT_FACTOR, BUSY_FACTOR]. Silent
# room widens drift, busy room narrows it. The narrowing on a busy room
# is intentional — when the audience makes noise, the piece pulls inward,
# does not compete.
ROOM_LOUDNESS_FLOOR = 0.02   # below this = pure silence
ROOM_LOUDNESS_CEIL = 0.15   # above this = saturated busy room
SILENT_WANDER_FACTOR = 1.6  # silence opens drift wider
BUSY_WANDER_FACTOR = 0.7    # busy narrows drift, piece refuses to compete

# Profile freshness — bridge's poller cares about mtime; we set this to
# stamp the profile so the next poll picks us up. Keep TTL > write period
# so the bridge never sees an "expired" chord.
EXPIRES_IN_SECONDS = 30


# --- Helpers -------------------------------------------------------------------

def clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


def lerp(t: float, lo: float, hi: float) -> float:
    return lo + (hi - lo) * clamp(t, 0.0, 1.0)


def read_scene(status_path: Path) -> tuple[float, dict[str, Any]]:
    """Return (density, raw_scene) from the bridge's status JSON."""
    try:
        data = json.loads(status_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return 0.0, {}
    scene = data.get("person_scene") or {}
    count_norm = float(scene.get("count_norm") or 0.0)
    activity = float(scene.get("activity") or 0.0)
    # Same weighting we planned for the source change so the live behavior
    # matches the documented intent: bodies count more than motion, but
    # both reinforce each other in a busy room.
    density = clamp(0.65 * count_norm + 0.35 * activity, 0.0, 1.0)
    return density, scene


def read_room_loudness(probe_path: Path) -> float:
    """Return current room RMS from the LisbonAudioProbe status JSON.

    Returns 0.0 if the probe file is missing, stale, malformed, or marks
    itself not-ok. The probe writes timestamp + last_update_age_ms; if
    the file hasn't been touched recently the room is unobserved, which
    is treated as silence for the purposes of widening the wander.
    """
    try:
        data = json.loads(probe_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return 0.0
    if not data.get("ok", False):
        return 0.0
    rms = data.get("rms")
    if rms is None:
        return 0.0
    return clamp(float(rms), 0.0, 1.0)


def loudness_to_wander_factor(loudness: float) -> float:
    """Map smoothed room loudness to a wander multiplier.

    Below ROOM_LOUDNESS_FLOOR  -> SILENT_WANDER_FACTOR (widen drift)
    Above ROOM_LOUDNESS_CEIL   -> BUSY_WANDER_FACTOR (narrow drift)
    Linear between the two endpoints.
    """
    if loudness <= ROOM_LOUDNESS_FLOOR:
        return SILENT_WANDER_FACTOR
    if loudness >= ROOM_LOUDNESS_CEIL:
        return BUSY_WANDER_FACTOR
    t = (loudness - ROOM_LOUDNESS_FLOOR) / (ROOM_LOUDNESS_CEIL - ROOM_LOUDNESS_FLOOR)
    return lerp(t, SILENT_WANDER_FACTOR, BUSY_WANDER_FACTOR)


def read_base_profile(profile_path: Path) -> dict[str, Any]:
    """Read the current profile as BASE, or fall back to a minimal seed."""
    try:
        return json.loads(profile_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {
            "schema": "lisbon.heuristic_profile.v1",
            "profile_id": "realtime-driver-fallback",
            "source": "realtime_chord_driver",
            "reason": "no base profile present, using minimal seed",
            "family": "balanced",
            "mode_bias": "balanced",
            "chord": {},
        }


def pick_voicing(density: float, current_voicing: str | None) -> str:
    """Hysteresis-stable voicing pick.

    If density is comfortably inside the current band (>= HYST from either
    edge), keep it. Otherwise pick the band density actually falls in.
    """
    if current_voicing is not None:
        for lo, hi, name in VOICING_BANDS:
            if name == current_voicing:
                if lo - VOICING_HYSTERESIS <= density <= hi + VOICING_HYSTERESIS:
                    return name
                break
    for lo, hi, name in VOICING_BANDS:
        if lo <= density <= hi:
            return name
    return VOICING_BANDS[-1][2]


def derive_chord(density: float, current_voicing: str | None, wander_factor: float = 1.0) -> dict[str, Any]:
    voicing = pick_voicing(density, current_voicing)
    root = lerp(density, ROOT_SEMITONES_MIN, ROOT_SEMITONES_MAX)
    wander = lerp(density, WANDER_MIN, WANDER_MAX) * wander_factor
    # Hard cap so the multiplied wander cannot drive the SWN voices into
    # pitches outside the dirge band — wander multiplies AROUND the root,
    # so a 1.6x multiplier with WANDER_MAX = 0.55 gives 0.88, still well
    # under the 1.0 hard ceiling the SWN respects.
    wander = clamp(wander, 0.0, 1.0)
    smoothing = lerp(density, SMOOTHING_MIN, SMOOTHING_MAX)
    return {
        "voicing": voicing,
        "root_semitones": round(root, 4),
        "pitch_wander_scale": round(wander, 4),
        "smoothing_hz": round(smoothing, 4),
        # transition_seconds left out so chord_palette picks its default
        # (30s glacial crossfade). The realtime driver doesn't try to
        # control transition speed — that's a slow-loop concern.
    }


def write_profile_atomic(profile_path: Path, profile: dict[str, Any]) -> None:
    """Atomic write: same dir, rename. Guarantees bridge sees a complete file."""
    tmp_path = profile_path.with_suffix(profile_path.suffix + ".realtime.tmp")
    tmp_path.write_text(json.dumps(profile, indent=2, sort_keys=True), encoding="utf-8")
    os.replace(tmp_path, profile_path)


# --- Main loop -----------------------------------------------------------------

def run(
    *,
    status_path: Path,
    profile_path: Path,
    period_seconds: float,
    log_every: int,
    stop_event: dict[str, bool],
    room_probe_path: Path | None = None,
) -> None:
    density_state = 0.0
    # 6/5 r5: room loudness EMA state for silence-widens-wander logic.
    # Initialized at the floor (treat startup as quiet — the piece begins
    # introverted, the room earns its restlessness).
    room_loudness_state = ROOM_LOUDNESS_FLOOR
    last_voicing: str | None = None
    last_log = 0.0
    tick = 0
    last_dt_clock = time.monotonic()
    print(
        f"[realtime] driver started. status={status_path.name} "
        f"profile={profile_path.name} period={period_seconds:.2f}s "
        f"room_probe={room_probe_path.name if room_probe_path else 'none'}",
        flush=True,
    )
    while not stop_event["stop"]:
        now = time.monotonic()
        dt = max(0.0, now - last_dt_clock)
        last_dt_clock = now

        density_raw, _scene = read_scene(status_path)
        # One-pole EMA on density to absorb YOLO bbox flicker.
        if dt > 0.0:
            import math
            alpha = 1.0 - math.exp(-DENSITY_EMA_HZ * dt)
        else:
            alpha = 1.0
        density_state = density_state + (density_raw - density_state) * clamp(alpha, 0.0, 1.0)

        # 6/5 r5: slow EMA on room loudness. Separate timescale (~60s)
        # so the wander breathes with the room over ceremony-time, not
        # frame-time. When the probe is missing the read returns 0.0
        # which the EMA pulls toward — silence widens drift, the piece
        # opens up when nothing is listening.
        if room_probe_path is not None:
            loudness_raw = read_room_loudness(room_probe_path)
            if dt > 0.0:
                import math
                room_alpha = 1.0 - math.exp(-ROOM_LOUDNESS_EMA_HZ * dt)
            else:
                room_alpha = 1.0
            room_loudness_state = (
                room_loudness_state
                + (loudness_raw - room_loudness_state) * clamp(room_alpha, 0.0, 1.0)
            )
            wander_factor = loudness_to_wander_factor(room_loudness_state)
        else:
            loudness_raw = 0.0
            wander_factor = 1.0

        base = read_base_profile(profile_path)
        chord = derive_chord(density_state, last_voicing, wander_factor=wander_factor)
        if chord["voicing"] != last_voicing:
            print(
                f"[realtime] voicing change {last_voicing} -> {chord['voicing']} "
                f"@ density {density_state:.3f}",
                flush=True,
            )
            last_voicing = chord["voicing"]

        # Merge: take BASE, override chord, refresh expires_at, stamp source.
        merged = dict(base)
        merged["chord"] = chord
        expires_at = datetime.now(tz=timezone.utc) + timedelta(seconds=EXPIRES_IN_SECONDS)
        merged["expires_at"] = expires_at.strftime("%Y-%m-%dT%H:%M:%SZ")
        # Stamp source so we can tell at a glance who wrote the file last.
        merged["realtime_driver"] = {
            "density": round(density_state, 4),
            "density_raw": round(density_raw, 4),
            "room_loudness": round(room_loudness_state, 4),
            "room_loudness_raw": round(loudness_raw, 4),
            "wander_factor": round(wander_factor, 3),
            "ts": datetime.now(tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        }

        try:
            write_profile_atomic(profile_path, merged)
        except OSError as exc:
            print(f"[realtime] write error: {exc!r}", flush=True)

        tick += 1
        if tick % log_every == 0 and (now - last_log) > 1.0:
            print(
                f"[realtime] tick={tick} density={density_state:.3f} "
                f"voicing={chord['voicing']} root={chord['root_semitones']:.2f} "
                f"wander={chord['pitch_wander_scale']:.2f} "
                f"room_rms={room_loudness_state:.3f} factor={wander_factor:.2f}",
                flush=True,
            )
            last_log = now

        # Sleep period. We yield in small slices so SIGTERM lands quickly.
        slice_dt = 0.05
        slept = 0.0
        while slept < period_seconds and not stop_event["stop"]:
            time.sleep(slice_dt)
            slept += slice_dt


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--status-path",
        type=Path,
        default=Path(__file__).resolve().parent
        / "runtime"
        / "swn_camera_soundscape_status.json",
        help="path to the bridge's live status JSON",
    )
    parser.add_argument(
        "--profile-path",
        type=Path,
        default=Path(__file__).resolve().parent
        / "runtime"
        / "heuristic_profile.json",
        help="path to the heuristic profile to merge into and rewrite",
    )
    parser.add_argument(
        "--period-seconds",
        type=float,
        default=0.75,
        help="write cadence (default 0.75s — slightly faster than bridge's 1Hz poll)",
    )
    parser.add_argument(
        "--log-every",
        type=int,
        default=8,
        help="emit a status line every N ticks (default 8 = ~6s at 0.75s period)",
    )
    parser.add_argument(
        "--room-probe-path",
        type=Path,
        default=Path(__file__).resolve().parent
        / "runtime"
        / "room_audio_probe_status.json",
        help="path to LisbonAudioProbe status JSON for silence-widens-wander logic. Pass empty string to disable.",
    )
    args = parser.parse_args(argv)

    # Empty string from CLI disables the room probe entirely.
    room_probe_path = args.room_probe_path if str(args.room_probe_path) else None

    stop_event = {"stop": False}

    def handle_signal(_signum, _frame):
        print("[realtime] stop requested; finishing tick", flush=True)
        stop_event["stop"] = True

    signal.signal(signal.SIGINT, handle_signal)
    signal.signal(signal.SIGTERM, handle_signal)

    try:
        run(
            status_path=args.status_path,
            profile_path=args.profile_path,
            period_seconds=args.period_seconds,
            log_every=args.log_every,
            stop_event=stop_event,
            room_probe_path=room_probe_path,
        )
    finally:
        print("[realtime] driver stopped", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
