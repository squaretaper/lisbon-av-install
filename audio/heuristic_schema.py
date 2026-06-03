"""Shared schema bounds and atomic writer for `lisbon.heuristic_profile.v1`.

This module is the single source of truth for what numeric ranges a profile
may carry. The reflective reviewer (deterministic or agentic) clamps every
field it writes against these bounds. The bridge consumer is allowed to
re-clamp on read; both layers being defensive is intentional.

Keep this module dependency-free (stdlib only) so it can be imported from
cron contexts, tests, and the bridge alike.
"""
from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


SCHEMA_NAME = "lisbon.heuristic_profile.v1"

# (lo, hi) inclusive bounds. Anything outside is clamped on write.
# Keys mirror the JSON schema in docs/10-reflective-agent-loop.md.
BOUNDS: dict[str, tuple[float, float]] = {
    "scene.silence_hold_seconds": (0.0, 60.0),
    "scene.density_target": (0.0, 1.0),
    "scene.avoid_repetition_seconds": (0.0, 300.0),
    "camera.movement_gate_sensitivity": (0.0, 1.0),
    "camera.stillness_deadband_scale": (0.5, 2.0),
    "camera.sector_activity_weight": (0.0, 1.0),
    "audio.drone_bias": (0.0, 1.0),
    "audio.glitch_probability": (0.0, 0.5),
    "audio.high_band_strobe_threshold_scale": (0.5, 1.5),
    "audio.feedback_suppression": (0.0, 1.0),
    "lights.brightness_ceiling": (32.0, 240.0),
    "lights.black_floor_bias": (0.0, 1.0),
    "lights.strobe_ceiling": (96.0, 255.0),
    "lights.packet_complexity": (0.0, 1.0),
    "cv.max_cv_scale": (0.4, 1.0),
    "cv.movement_gate_ceiling_v": (0.0, 5.0),
    "cv.pitch_drift_scale": (0.0, 1.0),
    # Chord layer — controls the SWN voices 1/2/3 V/oct positions.
    # root_semitones is offset from C0 (16.35 Hz). 24..48 = C2..B3.
    # The three voice_*_semitones are offsets from root; the bridge clamps the
    # sum (root + voice_offset) into the ES-9 normalized 1V/oct range.
    "chord.root_semitones": (0.0, 60.0),
    "chord.voice_1_semitones": (-12.0, 24.0),
    "chord.voice_2_semitones": (-12.0, 24.0),
    "chord.voice_3_semitones": (-12.0, 24.0),
    "chord.smoothing_hz": (0.05, 4.0),
    "chord.pitch_wander_scale": (0.0, 2.0),
}

ALLOWED_MODE_BIAS = {
    "balanced",
    "sparse_drone",
    "dense_response",
    "settle",
    "wake",
    "rest",
    "surprise",  # reserved for agent-initiated departures
}

ALLOWED_SOURCES = {"seed", "deterministic_reviewer", "reflective_agent", "manual"}

# Default lifetime of a written profile. Stale profiles self-disable.
DEFAULT_TTL_SECONDS = 600


@dataclass(frozen=True)
class ProfileWriteResult:
    path: Path
    profile_id: str
    history_path: Path


def _utc_iso(t: float) -> str:
    return datetime.fromtimestamp(t, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _clamp(value: float, lo: float, hi: float) -> float:
    if value < lo:
        return lo
    if value > hi:
        return hi
    return float(value)


def _walk_bounds(profile: dict, *, fill_missing_with: dict | None = None) -> dict:
    """Return a deep copy of `profile` with all numeric fields clamped.

    Missing fields are filled from `fill_missing_with` if provided, otherwise
    left absent (the bridge will use its own defaults).
    """
    fill = fill_missing_with or {}
    out: dict[str, Any] = json.loads(json.dumps(profile))  # cheap deep copy
    for dotted, (lo, hi) in BOUNDS.items():
        section, key = dotted.split(".", 1)
        section_dict = out.setdefault(section, {})
        if key in section_dict:
            section_dict[key] = _clamp(float(section_dict[key]), lo, hi)
        elif section in fill and key in fill[section]:
            section_dict[key] = _clamp(float(fill[section][key]), lo, hi)
    return out


def validate(profile: dict) -> list[str]:
    """Return a list of validation issues. Empty list = ok.

    This is a soft check: it never raises and never mutates the profile.
    """
    issues: list[str] = []
    if profile.get("schema") != SCHEMA_NAME:
        issues.append(f"schema must be {SCHEMA_NAME!r}; got {profile.get('schema')!r}")
    pid = profile.get("profile_id")
    if not isinstance(pid, str) or not pid:
        issues.append("profile_id must be a non-empty string")
    if "mode_bias" in profile and profile["mode_bias"] not in ALLOWED_MODE_BIAS:
        issues.append(f"mode_bias {profile['mode_bias']!r} not in {sorted(ALLOWED_MODE_BIAS)}")
    if "source" in profile and profile["source"] not in ALLOWED_SOURCES:
        issues.append(f"source {profile['source']!r} not in {sorted(ALLOWED_SOURCES)}")
    for dotted, (lo, hi) in BOUNDS.items():
        section, key = dotted.split(".", 1)
        section_dict = profile.get(section, {})
        if key in section_dict:
            try:
                v = float(section_dict[key])
            except (TypeError, ValueError):
                issues.append(f"{dotted}: not a number")
                continue
            if v < lo or v > hi:
                issues.append(f"{dotted}={v} outside [{lo}, {hi}]")
    return issues


def write_profile_atomic(
    profile: dict,
    *,
    runtime_dir: Path,
    history_filename: str = "profile_history.jsonl",
    profile_filename: str = "heuristic_profile.json",
    ttl_seconds: int = DEFAULT_TTL_SECONDS,
    now: float | None = None,
) -> ProfileWriteResult:
    """Clamp, stamp, write atomically, and append to history.

    The history append happens after the main write succeeds. If the history
    write fails we still consider the profile applied — the live file is the
    source of truth for the bridge.
    """
    now = time.time() if now is None else now
    runtime_dir.mkdir(parents=True, exist_ok=True)

    stamped = _walk_bounds(profile)
    stamped["schema"] = SCHEMA_NAME
    stamped.setdefault("profile_id", f"unnamed-{int(now)}")
    stamped["updated_at"] = _utc_iso(now)
    stamped["expires_at"] = _utc_iso(now + max(60, int(ttl_seconds)))
    stamped.setdefault("source", "deterministic_reviewer")

    target = runtime_dir / profile_filename
    tmp = target.with_suffix(target.suffix + ".tmp")
    tmp.write_text(json.dumps(stamped, indent=2, sort_keys=True) + "\n")
    os.replace(tmp, target)

    history_path = runtime_dir / history_filename
    try:
        with history_path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps({"event": "write", "profile": stamped}, sort_keys=True) + "\n")
    except OSError:
        pass

    return ProfileWriteResult(
        path=target,
        profile_id=str(stamped["profile_id"]),
        history_path=history_path,
    )


def append_history_event(
    runtime_dir: Path,
    event: str,
    payload: dict,
    *,
    history_filename: str = "profile_history.jsonl",
) -> None:
    """Append an arbitrary structured event to the history log.

    Used by the scorer (fitness scores), the reviewer (decision notes), and
    the agent path (arc memory). Never raises.
    """
    runtime_dir.mkdir(parents=True, exist_ok=True)
    history_path = runtime_dir / history_filename
    try:
        with history_path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps({"event": event, "ts": _utc_iso(time.time()), **payload}, sort_keys=True) + "\n")
    except OSError:
        pass


def read_history_tail(
    runtime_dir: Path,
    *,
    max_lines: int = 200,
    history_filename: str = "profile_history.jsonl",
) -> list[dict]:
    """Return up to `max_lines` most recent history entries, oldest first."""
    history_path = runtime_dir / history_filename
    if not history_path.exists():
        return []
    # Tail: read whole file if reasonably small, otherwise seek from end.
    size = history_path.stat().st_size
    if size < 256 * 1024:
        lines: Iterable[str] = history_path.read_text(encoding="utf-8").splitlines()
    else:
        with history_path.open("rb") as fh:
            fh.seek(-min(256 * 1024, size), os.SEEK_END)
            data = fh.read().decode("utf-8", errors="replace")
        lines = data.splitlines()[1:]  # drop possibly partial first line
    tail = list(lines)[-max_lines:]
    out: list[dict] = []
    for line in tail:
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out
