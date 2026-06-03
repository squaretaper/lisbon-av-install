"""Score a recent window of bridge telemetry against an applied profile.

Reads the rolling `swn_camera_soundscape_status.json` by sampling it on a
timer (no bridge changes required), and computes a small fitness score
that the reviewer uses to decide whether to hold, mutate, or swap.

This is deliberately tiny and explainable. The scorer never touches
hardware. It only reads JSON and appends a `score` event to history.

Fitness intent (v1):

  + breath        parameter variance in the response (system is alive)
  + listening     correlation between movement and CV/lights response
  - stuck         same mode_bias persisting past `stuck_seconds`
  - overshoot     strobe / brightness pinned at ceiling
  - dead          people present, response variance ~ 0

The score is a single float in roughly [-1.0, +1.0]. Negative = something
is off and the reviewer should consider mutating or swapping. Positive =
hold, or mutate gently.
"""
from __future__ import annotations

import argparse
import json
import math
import statistics
import time
from collections import deque
from pathlib import Path
from typing import Iterable

from .heuristic_schema import append_history_event, read_history_tail


def _safe_float(d: dict, *path: str, default: float = 0.0) -> float:
    cur: object = d
    for key in path:
        if not isinstance(cur, dict) or key not in cur:
            return default
        cur = cur[key]
    if isinstance(cur, (int, float, str)):
        try:
            return float(cur)
        except (TypeError, ValueError):
            return default
    return default


def _variance(values: Iterable[float]) -> float:
    seq = [float(v) for v in values]
    if len(seq) < 2:
        return 0.0
    return statistics.pvariance(seq)


def _correlation(xs: list[float], ys: list[float]) -> float:
    if len(xs) < 4 or len(xs) != len(ys):
        return 0.0
    mx = statistics.mean(xs)
    my = statistics.mean(ys)
    num = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    dx = math.sqrt(sum((x - mx) ** 2 for x in xs))
    dy = math.sqrt(sum((y - my) ** 2 for y in ys))
    if dx == 0 or dy == 0:
        return 0.0
    return max(-1.0, min(1.0, num / (dx * dy)))


def score_window(snapshots: list[dict], *, stuck_seconds: float = 240.0) -> dict:
    """Return a fitness dict for a list of bridge snapshots (oldest first)."""
    if not snapshots:
        return {"score": 0.0, "components": {}, "reason": "no snapshots"}

    movements: list[float] = []
    cv_movement_gate: list[float] = []
    cv_dispersion: list[float] = []
    brightness_proxy: list[float] = []
    people_counts: list[int] = []
    modes: list[str] = []
    strobe_pinned = 0
    bright_pinned = 0

    for snap in snapshots:
        ps = snap.get("person_scene") or {}
        movements.append(_safe_float(ps, "movement"))
        people_counts.append(int(_safe_float(ps, "people_count")))
        cv = snap.get("cv") or {}
        cv_movement_gate.append(_safe_float(cv, "cv7_movement_gate"))
        cv_dispersion.append(_safe_float(cv, "cv5_dispersion"))
        # Brightness proxy: use audio features when available, else feature motion.
        ai = snap.get("audio_input") or {}
        feat = snap.get("features") or {}
        brightness_proxy.append(_safe_float(ai, "rms", default=_safe_float(feat, "motion")))
        modes.append(str(snap.get("mode_bias") or snap.get("vision_mode") or "unknown"))
        # Detect ceiling pinning: features pinned high.
        if _safe_float(ai, "peak") >= 0.985:
            strobe_pinned += 1
        if _safe_float(feat, "brightness") >= 0.98:
            bright_pinned += 1

    breath = min(1.0, _variance(cv_movement_gate) * 6.0 + _variance(cv_dispersion) * 6.0)
    listening = _correlation(movements, cv_movement_gate)
    dead = 1.0 if (statistics.mean(people_counts or [0]) >= 1.0 and breath < 0.05) else 0.0
    overshoot = min(1.0, (strobe_pinned + bright_pinned) / max(1, len(snapshots)) * 2.0)

    # Stuck: longest run of the same mode in the window.
    longest_run = 1
    run = 1
    for a, b in zip(modes, modes[1:]):
        if a == b:
            run += 1
            longest_run = max(longest_run, run)
        else:
            run = 1
    span_seconds = max(1.0, _safe_float(snapshots[-1], "timestamp") - _safe_float(snapshots[0], "timestamp"))
    per_snap_seconds = span_seconds / max(1, len(snapshots))
    stuck = 1.0 if (longest_run * per_snap_seconds) >= stuck_seconds else 0.0

    components = {
        "breath": round(breath, 4),
        "listening": round(listening, 4),
        "dead": round(dead, 4),
        "overshoot": round(overshoot, 4),
        "stuck": round(stuck, 4),
        "samples": len(snapshots),
        "span_seconds": round(span_seconds, 2),
    }
    score = 0.45 * breath + 0.45 * listening - 0.35 * dead - 0.25 * overshoot - 0.25 * stuck
    score = max(-1.0, min(1.0, score))

    reasons = []
    if breath < 0.05:
        reasons.append("low breath (response is flat)")
    if listening > 0.4:
        reasons.append("clear movement-to-CV correlation")
    elif listening < -0.2:
        reasons.append("inverse correlation (response fighting movement)")
    if dead > 0:
        reasons.append("people present, response near zero")
    if overshoot > 0.4:
        reasons.append("ceilings pinned")
    if stuck > 0:
        reasons.append(f"mode unchanged for >= {stuck_seconds:.0f}s")
    if not reasons:
        reasons.append("nominal")

    return {"score": round(score, 4), "components": components, "reason": "; ".join(reasons)}


def sample_status(
    status_path: Path,
    *,
    seconds: float,
    period: float = 1.0,
) -> list[dict]:
    """Poll `status_path` for `seconds`, returning unique snapshots oldest-first."""
    deadline = time.time() + max(1.0, seconds)
    seen_ts: set[float] = set()
    buf: deque[dict] = deque(maxlen=max(8, int(seconds / max(0.25, period)) + 4))
    while time.time() < deadline:
        try:
            data = json.loads(status_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            time.sleep(period)
            continue
        ts = data.get("timestamp")
        if isinstance(ts, (int, float)) and ts not in seen_ts:
            seen_ts.add(float(ts))
            buf.append(data)
        time.sleep(period)
    return list(buf)


def main() -> int:
    ap = argparse.ArgumentParser(description="Score the recent bridge telemetry window.")
    ap.add_argument("--status-path", default="audio/runtime/swn_camera_soundscape_status.json")
    ap.add_argument("--runtime-dir", default="audio/runtime")
    ap.add_argument("--window-seconds", type=float, default=120.0)
    ap.add_argument("--sample-period", type=float, default=1.0)
    ap.add_argument("--print-only", action="store_true", help="do not append to history")
    args = ap.parse_args()

    snapshots = sample_status(
        Path(args.status_path),
        seconds=args.window_seconds,
        period=args.sample_period,
    )
    result = score_window(snapshots)

    # Attach the current profile_id (if any) so history is linkable.
    runtime_dir = Path(args.runtime_dir)
    profile_path = runtime_dir / "heuristic_profile.json"
    profile_id = None
    if profile_path.exists():
        try:
            profile_id = json.loads(profile_path.read_text(encoding="utf-8")).get("profile_id")
        except json.JSONDecodeError:
            pass
    result["profile_id"] = profile_id

    print(json.dumps(result, indent=2, sort_keys=True))
    if not args.print_only:
        append_history_event(runtime_dir, "score", result)
    # Silence the helper read_history_tail import-not-used; keep available for callers.
    _ = read_history_tail
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
