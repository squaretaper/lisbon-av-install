"""Lisbon reflective reviewer.

Slow loop. Reads the rolling bridge telemetry and the recent profile/score
history, and writes the next advisory profile.

Two operating modes:

  1) `decide`  (deterministic, default): classify the current window into one
     of the seed families, optionally mutate the parent within schema bounds,
     write the new profile. Safe to run from a cron without an agent.

  2) `agent-brief`: emit a single JSON blob to stdout summarizing room state,
     recent history, fitness scores, and the available seed families. An
     agent (e.g. me, woken by cron) reads this blob, picks a profile, and
     writes it via `apply-profile`.

The reviewer never opens audio, CV, serial, or the camera. It only reads
telemetry JSON and writes a profile JSON. The fast-loop bridge clamps
everything on read; the reviewer also clamps on write.
"""
from __future__ import annotations

import argparse
import json
import random
import statistics
import sys
import time
from pathlib import Path
from typing import Any

from .heuristic_schema import (
    BOUNDS,
    DEFAULT_TTL_SECONDS,
    append_history_event,
    read_history_tail,
    validate,
    write_profile_atomic,
)
from .profile_scorer import sample_status, score_window


# Map seed family -> profile filename (under audio/profiles/).
SEED_FAMILIES: dict[str, str] = {
    "balanced": "balanced-default.json",
    "sparse": "sparse-still-room.json",
    "dense": "busy-active-room.json",
    "corrective": "stuck-overactive.json",
    "wake": "dead-disengaged.json",
    "rest": "rest-floor.json",
}


def load_seed(profiles_dir: Path, family: str) -> dict:
    path = profiles_dir / SEED_FAMILIES[family]
    return json.loads(path.read_text(encoding="utf-8"))


def classify_window(snapshots: list[dict]) -> tuple[str, str]:
    """Pick a seed family for the current window. Returns (family, reason)."""
    if not snapshots:
        return "balanced", "no telemetry; defaulting to balanced"

    def avg(key_path: tuple[str, ...], default: float = 0.0) -> float:
        vals: list[float] = []
        for snap in snapshots:
            cur: Any = snap
            ok = True
            for k in key_path:
                if not isinstance(cur, dict) or k not in cur:
                    ok = False
                    break
                cur = cur[k]
            if ok and isinstance(cur, (int, float)):
                vals.append(float(cur))
        return statistics.mean(vals) if vals else default

    people = avg(("person_scene", "people_count"))
    movement = avg(("person_scene", "movement"))
    activity = avg(("person_scene", "activity"))
    frame_motion = avg(("features", "motion"))

    # Heuristics, deliberate and crude. The agent path can override.
    if people < 0.4 and movement < 0.05:
        return "sparse", f"few people ({people:.2f}), low movement ({movement:.2f})"
    if people >= 2.0 and (movement >= 0.18 or activity >= 0.3):
        return "dense", f"people={people:.2f}, movement={movement:.2f}, activity={activity:.2f}"
    if people >= 1.0 and movement < 0.04 and frame_motion >= 0.12:
        return "corrective", "frame motion present but bodies still; likely artifact"
    if people >= 1.0 and movement < 0.05 and activity < 0.05:
        return "wake", "people present but response variance is near zero"
    return "balanced", f"middle of the road (people={people:.2f}, movement={movement:.2f})"


def mutate(profile: dict, *, jitter: float = 0.12, rng: random.Random | None = None) -> dict:
    """Gaussian-jitter every numeric field by `jitter` * (hi - lo), clamped.

    Mode bias is preserved. Non-numeric fields are preserved. `profile_id` is
    suffixed `-mut`. The output is bounds-safe before writing.
    """
    rng = rng or random.Random()
    out: dict[str, Any] = json.loads(json.dumps(profile))
    for dotted, (lo, hi) in BOUNDS.items():
        section, key = dotted.split(".", 1)
        sec = out.setdefault(section, {})
        if key in sec and isinstance(sec[key], (int, float)):
            span = hi - lo
            sigma = max(1e-6, jitter * span)
            new_val = float(sec[key]) + rng.gauss(0.0, sigma)
            if new_val < lo:
                new_val = lo
            elif new_val > hi:
                new_val = hi
            sec[key] = round(new_val, 4)
    out["profile_id"] = f"{out.get('profile_id', 'unnamed')}-mut{int(time.time()) % 100000}"
    return out


def recent_fitness_by_family(history: list[dict]) -> dict[str, float]:
    """Average recent score per family. Empty for families never tried."""
    scores: dict[str, list[float]] = {}
    pid_to_family: dict[str, str] = {}
    for entry in history:
        if entry.get("event") == "write":
            prof = entry.get("profile") or {}
            pid = prof.get("profile_id")
            fam = prof.get("family")
            if isinstance(pid, str) and isinstance(fam, str):
                pid_to_family[pid] = fam
        elif entry.get("event") == "score":
            pid = entry.get("profile_id")
            family = pid_to_family.get(pid or "")
            score = entry.get("score")
            if family and isinstance(score, (int, float)):
                scores.setdefault(family, []).append(float(score))
    return {fam: round(statistics.mean(vals), 4) for fam, vals in scores.items()}


def build_agent_brief(
    *,
    snapshots: list[dict],
    history: list[dict],
    profiles_dir: Path,
) -> dict:
    """Compact JSON brief for an agent: room state, history, options."""
    family, reason = classify_window(snapshots)
    fitness = recent_fitness_by_family(history)

    # Last applied profile.
    last_profile: dict | None = None
    for entry in reversed(history):
        if entry.get("event") == "write":
            last_profile = entry.get("profile")
            break

    # Most recent score.
    last_score: dict | None = None
    for entry in reversed(history):
        if entry.get("event") == "score":
            last_score = entry
            break

    # Current room summary from the last snapshot.
    current: dict = {}
    if snapshots:
        last = snapshots[-1]
        ps = last.get("person_scene") or {}
        ai = last.get("audio_input") or {}
        feat = last.get("features") or {}
        current = {
            "people_count": ps.get("people_count"),
            "movement": ps.get("movement"),
            "activity": ps.get("activity"),
            "centroid_x": ps.get("centroid_x"),
            "centroid_y": ps.get("centroid_y"),
            "audio_rms": ai.get("rms"),
            "audio_peak": ai.get("peak"),
            "frame_motion": feat.get("motion"),
            "frame_brightness": feat.get("brightness"),
            "timestamp": last.get("timestamp"),
        }

    return {
        "now": time.time(),
        "samples_in_window": len(snapshots),
        "deterministic_pick": {"family": family, "reason": reason},
        "fitness_by_family": fitness,
        "last_profile": last_profile,
        "last_score": last_score,
        "current_room": current,
        "available_families": sorted(SEED_FAMILIES.keys()),
        "schema_bounds": {k: list(v) for k, v in BOUNDS.items()},
        "instructions": (
            "You are the slow-loop composer for the Lisbon install. "
            "Pick a family from `available_families`, optionally mutate it within `schema_bounds`, "
            "or write a fully custom profile. Use `apply-profile` to write it. "
            "Prefer rest after long busy stretches, prefer surprise after long stretches of the same family. "
            "Do not write the same family twice in a row unless the room demands it."
        ),
    }


def write_decision_profile(
    *,
    runtime_dir: Path,
    profiles_dir: Path,
    family: str,
    reason: str,
    mutate_jitter: float,
    rng: random.Random,
    ttl_seconds: int,
    source: str,
) -> dict:
    seed = load_seed(profiles_dir, family)
    candidate = mutate(seed, jitter=mutate_jitter, rng=rng) if mutate_jitter > 0 else seed
    candidate["source"] = source
    candidate["reason"] = f"[{family}] {reason}"
    candidate["family"] = family
    issues = validate(candidate)
    if issues:
        append_history_event(runtime_dir, "validation_warning", {"issues": issues, "candidate_id": candidate.get("profile_id")})
    result = write_profile_atomic(candidate, runtime_dir=runtime_dir, ttl_seconds=ttl_seconds)
    append_history_event(
        runtime_dir,
        "decision",
        {
            "profile_id": result.profile_id,
            "family": family,
            "reason": reason,
            "source": source,
            "jitter": mutate_jitter,
        },
    )
    return candidate


def cmd_decide(args: argparse.Namespace) -> int:
    runtime_dir = Path(args.runtime_dir)
    profiles_dir = Path(args.profiles_dir)
    snapshots = sample_status(
        Path(args.status_path),
        seconds=args.window_seconds,
        period=args.sample_period,
    )
    if args.score_window:
        score = score_window(snapshots)
        append_history_event(runtime_dir, "score", score)
        print(json.dumps({"score": score}, indent=2, sort_keys=True), file=sys.stderr)

    family, reason = classify_window(snapshots)
    rng = random.Random(args.seed) if args.seed is not None else random.Random()
    written = write_decision_profile(
        runtime_dir=runtime_dir,
        profiles_dir=profiles_dir,
        family=family,
        reason=reason,
        mutate_jitter=args.jitter,
        rng=rng,
        ttl_seconds=args.ttl_seconds,
        source="deterministic_reviewer",
    )
    print(json.dumps({"applied": written}, indent=2, sort_keys=True))
    return 0


def cmd_agent_brief(args: argparse.Namespace) -> int:
    runtime_dir = Path(args.runtime_dir)
    profiles_dir = Path(args.profiles_dir)
    snapshots = sample_status(
        Path(args.status_path),
        seconds=args.window_seconds,
        period=args.sample_period,
    )
    history = read_history_tail(runtime_dir, max_lines=args.history_lines)
    brief = build_agent_brief(snapshots=snapshots, history=history, profiles_dir=profiles_dir)
    print(json.dumps(brief, indent=2, sort_keys=True))
    return 0


def cmd_apply_profile(args: argparse.Namespace) -> int:
    runtime_dir = Path(args.runtime_dir)
    if args.from_file:
        candidate = json.loads(Path(args.from_file).read_text(encoding="utf-8"))
    else:
        candidate = json.loads(sys.stdin.read())
    candidate.setdefault("source", "reflective_agent")
    issues = validate(candidate)
    if issues and not args.force:
        print(json.dumps({"rejected": True, "issues": issues}, indent=2), file=sys.stderr)
        return 2
    result = write_profile_atomic(candidate, runtime_dir=runtime_dir, ttl_seconds=args.ttl_seconds)
    append_history_event(
        runtime_dir,
        "decision",
        {
            "profile_id": result.profile_id,
            "family": candidate.get("family"),
            "reason": candidate.get("reason"),
            "source": candidate.get("source"),
            "mode_bias": candidate.get("mode_bias"),
        },
    )
    print(json.dumps({"applied_profile_id": result.profile_id, "path": str(result.path)}, indent=2))
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Lisbon reflective reviewer.")
    sub = p.add_subparsers(dest="command", required=True)

    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--status-path", default="audio/runtime/swn_camera_soundscape_status.json")
    common.add_argument("--runtime-dir", default="audio/runtime")
    common.add_argument("--profiles-dir", default="audio/profiles")
    common.add_argument("--window-seconds", type=float, default=120.0)
    common.add_argument("--sample-period", type=float, default=1.0)

    d = sub.add_parser("decide", parents=[common], help="Deterministic pick + mutate + write.")
    d.add_argument("--jitter", type=float, default=0.08, help="0 = pure seed, 0.2 = lively. Clamped on write.")
    d.add_argument("--ttl-seconds", type=int, default=DEFAULT_TTL_SECONDS)
    d.add_argument("--seed", type=int, default=None, help="RNG seed for reproducible mutations (tests).")
    d.add_argument("--score-window", action="store_true", help="Also score the window and append to history.")
    d.set_defaults(func=cmd_decide)

    a = sub.add_parser("agent-brief", parents=[common], help="Emit JSON context for an agent to read.")
    a.add_argument("--history-lines", type=int, default=200)
    a.set_defaults(func=cmd_agent_brief)

    ap = sub.add_parser("apply-profile", help="Read a profile (file or stdin) and write it as the live profile.")
    ap.add_argument("--runtime-dir", default="audio/runtime")
    ap.add_argument("--from-file", default=None)
    ap.add_argument("--ttl-seconds", type=int, default=DEFAULT_TTL_SECONDS)
    ap.add_argument("--force", action="store_true", help="Bypass validation issues (still clamps numerics).")
    ap.set_defaults(func=cmd_apply_profile)

    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
