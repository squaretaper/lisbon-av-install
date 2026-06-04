#!/usr/bin/env python3
"""Live tuner — merge a `tune` block into heuristic_profile.json without restart.

Operator 6/4 r13: stop paying a bridge restart for every threshold tweak.

The bridge polls audio/runtime/heuristic_profile.json once per second
and now applies any `tune` block to live detector + mapper knobs through
PersonSceneTracker.set_tuning and HumanAwareSwnMapper.set_tuning. This
script atomically merges new tune values into the profile so the next
bridge poll picks them up — total round-trip ≤1.3s, zero CV freeze.

Supported keys (current set; extend as new knobs become hot-tunable):

  stillness_deadband        float, planar+distance delta below which
                            movement signal is gated to 0 (typical 0.005-0.05)
  tracker_match_threshold   float, centroid distance threshold for cross-id
                            track state inheritance (typical 0.20-0.50)
  glitch_fire_threshold     float, movement value above which CV7 fires to
                            max_cv (typical 0.02-0.10)
  browse_rate_min_hz        float, CV4 browse LFO rate at empty room
                            (typical 0.005-0.05)
  browse_rate_max_hz        float, CV4 browse LFO rate at full active room
                            (typical 0.05-0.20)

Usage:
  scripts/tune.py glitch_fire_threshold=0.02
  scripts/tune.py stillness_deadband=0.006 tracker_match_threshold=0.45
  scripts/tune.py --show                                # print current tune block
  scripts/tune.py --clear                               # remove tune block entirely
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

PROFILE_PATH = Path(__file__).resolve().parent.parent / "audio" / "runtime" / "heuristic_profile.json"

ALLOWED_KEYS = {
    "stillness_deadband",
    "tracker_match_threshold",
    "glitch_fire_threshold",
    "browse_rate_min_hz",
    "browse_rate_max_hz",
    "cv7_hold_ms",
    "cv7_release_ms",
}


def load_profile() -> dict:
    try:
        return json.loads(PROFILE_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"error reading {PROFILE_PATH}: {exc}", file=sys.stderr)
        sys.exit(2)


def write_profile_atomic(profile: dict) -> None:
    tmp_path = PROFILE_PATH.with_suffix(PROFILE_PATH.suffix + ".tune.tmp")
    tmp_path.write_text(json.dumps(profile, indent=2, sort_keys=True), encoding="utf-8")
    os.replace(tmp_path, PROFILE_PATH)


def show() -> None:
    profile = load_profile()
    tune = profile.get("tune") or {}
    if not tune:
        print("(no tune block set)")
        return
    print(json.dumps(tune, indent=2, sort_keys=True))


def clear() -> None:
    profile = load_profile()
    if "tune" not in profile:
        print("(no tune block to clear)")
        return
    profile.pop("tune", None)
    write_profile_atomic(profile)
    print("cleared tune block")


def apply(pairs: list[str]) -> None:
    profile = load_profile()
    tune = dict(profile.get("tune") or {})
    for pair in pairs:
        if "=" not in pair:
            print(f"bad pair '{pair}' — expected key=value", file=sys.stderr)
            sys.exit(2)
        key, _, value_str = pair.partition("=")
        if key not in ALLOWED_KEYS:
            print(f"unknown key '{key}' — allowed: {sorted(ALLOWED_KEYS)}", file=sys.stderr)
            sys.exit(2)
        try:
            tune[key] = float(value_str)
        except ValueError:
            print(f"value '{value_str}' for '{key}' is not a float", file=sys.stderr)
            sys.exit(2)
    profile["tune"] = tune
    write_profile_atomic(profile)
    print(f"merged tune block: {json.dumps(tune, sort_keys=True)}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--show", action="store_true", help="print current tune block and exit")
    parser.add_argument("--clear", action="store_true", help="remove tune block entirely and exit")
    parser.add_argument("pairs", nargs="*", help="key=value pairs to merge into the tune block")
    args = parser.parse_args(argv)

    if args.show:
        show()
    elif args.clear:
        clear()
    elif args.pairs:
        apply(args.pairs)
    else:
        parser.print_help()
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
