#!/usr/bin/env python3
"""Live tuner — write hot-tunable knobs to an isolated file.

Operator 6/4 r13: stop paying a bridge restart for every threshold tweak.
Operator 6/4 r16: split tune state into its own file to eliminate the
read-modify-write race between tune.py and the realtime chord driver.
Both used to touch heuristic_profile.json every 750ms, and the driver's
stale-snapshot writes could clobber tune updates.

Now: tune.py writes ONLY audio/runtime/tune.json. The bridge polls that
file directly. The chord driver still owns heuristic_profile.json and
never touches tune state. No more contention, no migration needed for
the chord driver, no shared state to lock.

Supported keys:
  stillness_deadband        movement gate below which signal is 0
  tracker_match_threshold   centroid distance for cross-id inheritance
  glitch_fire_threshold     movement value above which CV7 fires
  browse_rate_min_hz        CV4 LFO rate at empty room
  browse_rate_max_hz        CV4 LFO rate at full active room
  cv7_hold_ms               full max_cv hold after glitch trigger
  cv7_release_ms            exp-decay tau after hold expires

Usage:
  scripts/tune.py glitch_fire_threshold=0.02
  scripts/tune.py stillness_deadband=0.006 tracker_match_threshold=0.45
  scripts/tune.py --show
  scripts/tune.py --clear
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
TUNE_PATH = REPO_ROOT / "audio" / "runtime" / "tune.json"
LEGACY_PROFILE_PATH = REPO_ROOT / "audio" / "runtime" / "heuristic_profile.json"

ALLOWED_KEYS = {
    "stillness_deadband",
    "tracker_match_threshold",
    "glitch_fire_threshold",
    "browse_rate_min_hz",
    "browse_rate_max_hz",
    "cv7_hold_ms",
    "cv7_release_ms",
    "movement_source",
}

# Keys that take a string value (must NOT be coerced to float). Everything
# else is treated as a numeric scalar.
STRING_KEYS = {"movement_source"}
STRING_KEY_ALLOWED_VALUES: dict[str, set[str]] = {
    "movement_source": {"bbox", "pose", "pose_raise", "bbox_raise", "arm_extension"},
}


def load_tune() -> dict:
    """Read current tune file. Empty dict if missing or invalid."""
    if not TUNE_PATH.exists():
        return {}
    try:
        data = json.loads(TUNE_PATH.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError) as exc:
        print(f"error reading {TUNE_PATH}: {exc}", file=sys.stderr)
        sys.exit(2)


def write_tune_atomic(tune: dict) -> None:
    TUNE_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = TUNE_PATH.with_suffix(TUNE_PATH.suffix + ".tmp")
    tmp_path.write_text(json.dumps(tune, indent=2, sort_keys=True), encoding="utf-8")
    os.replace(tmp_path, TUNE_PATH)


def clear_legacy_tune_in_profile() -> None:
    """One-shot migration helper: if a `tune` block still lingers in
    heuristic_profile.json from before the split, remove it so the
    bridge doesn't get conflicting values from two sources. Safe to
    call repeatedly; no-op when there's nothing to clear.
    """
    if not LEGACY_PROFILE_PATH.exists():
        return
    try:
        profile = json.loads(LEGACY_PROFILE_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return
    if "tune" not in profile:
        return
    profile.pop("tune", None)
    tmp_path = LEGACY_PROFILE_PATH.with_suffix(LEGACY_PROFILE_PATH.suffix + ".tune-migrate.tmp")
    tmp_path.write_text(json.dumps(profile, indent=2, sort_keys=True), encoding="utf-8")
    os.replace(tmp_path, LEGACY_PROFILE_PATH)
    print(f"(migrated stale `tune` block out of {LEGACY_PROFILE_PATH.name})")


def show() -> None:
    tune = load_tune()
    if not tune:
        print("(no tune values set)")
        return
    print(json.dumps(tune, indent=2, sort_keys=True))


def clear() -> None:
    if not TUNE_PATH.exists():
        print("(no tune file to clear)")
        return
    write_tune_atomic({})
    print("cleared tune values")


def apply(pairs: list[str]) -> None:
    # First-time use: migrate any leftover tune block out of the legacy
    # profile so we don't end up with two competing tune sources.
    clear_legacy_tune_in_profile()
    tune = load_tune()
    for pair in pairs:
        if "=" not in pair:
            print(f"bad pair '{pair}' — expected key=value", file=sys.stderr)
            sys.exit(2)
        key, _, value_str = pair.partition("=")
        if key not in ALLOWED_KEYS:
            print(f"unknown key '{key}' — allowed: {sorted(ALLOWED_KEYS)}", file=sys.stderr)
            sys.exit(2)
        try:
            if key in STRING_KEYS:
                normalised = value_str.lower().strip()
                allowed = STRING_KEY_ALLOWED_VALUES.get(key)
                if allowed and normalised not in allowed:
                    print(
                        f"value '{value_str}' for '{key}' not in allowed set {sorted(allowed)}",
                        file=sys.stderr,
                    )
                    sys.exit(2)
                tune[key] = normalised
            else:
                tune[key] = float(value_str)
        except ValueError:
            print(f"value '{value_str}' for '{key}' is not a float", file=sys.stderr)
            sys.exit(2)
    write_tune_atomic(tune)
    print(f"wrote tune file: {json.dumps(tune, sort_keys=True)}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--show", action="store_true", help="print current tune values and exit")
    parser.add_argument("--clear", action="store_true", help="remove all tune values and exit")
    parser.add_argument("pairs", nargs="*", help="key=value pairs to merge into the tune file")
    args = parser.parse_args(argv)

    if args.show:
        show()
    elif args.clear:
        clear()
    elif args.pairs:
        apply(args.pairs)
    else:
        parser.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
