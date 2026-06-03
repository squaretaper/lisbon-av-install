"""Tests for the deterministic reviewer + scorer + schema layer.

These tests never open hardware. They synthesize snapshots, drive the
classifier and mutator, and confirm the on-disk profile is bounds-safe.
"""
from __future__ import annotations

import json
import random
import time
from pathlib import Path

import pytest

from audio.heuristic_schema import (
    BOUNDS,
    SCHEMA_NAME,
    append_history_event,
    read_history_tail,
    validate,
    write_profile_atomic,
)
from audio.profile_scorer import score_window
from audio.reflective_reviewer import (
    SEED_FAMILIES,
    build_agent_brief,
    classify_window,
    load_seed,
    mutate,
    recent_fitness_by_family,
)


REPO_PROFILES = Path(__file__).resolve().parents[1] / "audio" / "profiles"


def _snapshot(*, ts: float, people: int, movement: float, activity: float = 0.0, mode: str = "balanced", **extra) -> dict:
    base = {
        "timestamp": ts,
        "person_scene": {
            "people_count": people,
            "movement": movement,
            "activity": activity,
            "centroid_x": 0.5,
            "centroid_y": 0.5,
        },
        "features": {"brightness": 0.4, "motion": movement, "centroid_x": 0.5, "centroid_y": 0.5},
        "audio_input": {"rms": 0.2, "peak": 0.5},
        "cv": {"cv7_movement_gate": movement * 2.0, "cv5_dispersion": activity},
        "mode_bias": mode,
    }
    base.update(extra)
    return base


# ---------- schema ----------

def test_seed_profiles_validate():
    for family, fname in SEED_FAMILIES.items():
        profile = json.loads((REPO_PROFILES / fname).read_text())
        assert profile["schema"] == SCHEMA_NAME
        assert validate(profile) == [], f"{family} has issues: {validate(profile)}"


def test_write_clamps_out_of_range(tmp_path: Path):
    bad = {
        "schema": SCHEMA_NAME,
        "profile_id": "bad-001",
        "lights": {"brightness_ceiling": 9000, "strobe_ceiling": -50},
        "audio": {"glitch_probability": 5.0},
        "cv": {"max_cv_scale": 99},
    }
    result = write_profile_atomic(bad, runtime_dir=tmp_path)
    written = json.loads(result.path.read_text())
    assert written["lights"]["brightness_ceiling"] == BOUNDS["lights.brightness_ceiling"][1]
    assert written["lights"]["strobe_ceiling"] == BOUNDS["lights.strobe_ceiling"][0]
    assert written["audio"]["glitch_probability"] == BOUNDS["audio.glitch_probability"][1]
    assert written["cv"]["max_cv_scale"] == BOUNDS["cv.max_cv_scale"][1]
    assert "updated_at" in written and "expires_at" in written


def test_history_roundtrip(tmp_path: Path):
    append_history_event(tmp_path, "test", {"foo": 1})
    append_history_event(tmp_path, "test", {"foo": 2})
    entries = read_history_tail(tmp_path)
    assert [e["foo"] for e in entries] == [1, 2]
    assert all(e["event"] == "test" for e in entries)


# ---------- classifier ----------

@pytest.mark.parametrize(
    "shape,expected",
    [
        ([(0, 0.01)] * 8, "sparse"),
        ([(3, 0.25, 0.4)] * 8, "dense"),
        ([(2, 0.005, 0.01)] * 8, "wake"),
        ([], "balanced"),
    ],
)
def test_classify(shape, expected):
    snaps = [
        _snapshot(ts=time.time() + i, people=p[0], movement=p[1], activity=p[2] if len(p) > 2 else 0.0)
        for i, p in enumerate(shape)
    ]
    family, _ = classify_window(snaps)
    assert family == expected


def test_classify_corrective_artifact_path():
    # Person present, body not moving, but the frame motion is high (artifact).
    snaps = [
        _snapshot(ts=time.time() + i, people=1, movement=0.0, activity=0.0)
        for i in range(8)
    ]
    for s in snaps:
        s["features"]["motion"] = 0.2
    family, _ = classify_window(snaps)
    assert family == "corrective"


# ---------- mutation ----------

def test_mutate_stays_in_bounds():
    rng = random.Random(42)
    for fname in SEED_FAMILIES.values():
        seed = json.loads((REPO_PROFILES / fname).read_text())
        for _ in range(50):
            mutated = mutate(seed, jitter=0.3, rng=rng)
            assert validate(mutated) == [], f"out-of-bounds mutation: {validate(mutated)}"


def test_mutate_changes_values():
    rng = random.Random(7)
    seed = load_seed(REPO_PROFILES, "balanced")
    mutated = mutate(seed, jitter=0.2, rng=rng)
    # At least one numeric field should differ.
    diffs = 0
    for dotted in BOUNDS:
        section, key = dotted.split(".", 1)
        if mutated.get(section, {}).get(key) != seed.get(section, {}).get(key):
            diffs += 1
    assert diffs > 0


# ---------- scorer ----------

def test_score_window_dead_room():
    base_ts = time.time()
    snaps = [_snapshot(ts=base_ts + i, people=2, movement=0.0) for i in range(20)]
    # Zero variance in CV → low breath, dead penalty triggers.
    result = score_window(snaps)
    assert result["components"]["dead"] == 1.0
    assert result["score"] < 0.0


def test_score_window_listening_room():
    base_ts = time.time()
    # Make movement and CV correlate strongly.
    snaps = []
    for i in range(20):
        mv = 0.05 + (i % 5) * 0.05
        snap = _snapshot(ts=base_ts + i, people=2, movement=mv, activity=0.2)
        snap["cv"]["cv7_movement_gate"] = mv * 3.0  # perfect linear
        snap["cv"]["cv5_dispersion"] = 0.2 + (i % 3) * 0.1
        snaps.append(snap)
    result = score_window(snaps)
    assert result["components"]["listening"] > 0.5
    assert result["score"] > 0.0


# ---------- agent brief ----------

def test_agent_brief_shape(tmp_path: Path):
    snaps = [_snapshot(ts=time.time() + i, people=0, movement=0.0) for i in range(6)]
    # Pre-seed history with one write + one score.
    write_profile_atomic(load_seed(REPO_PROFILES, "balanced"), runtime_dir=tmp_path)
    append_history_event(tmp_path, "score", {"score": 0.5, "profile_id": "seed-balanced-default"})
    history = read_history_tail(tmp_path)
    brief = build_agent_brief(snapshots=snaps, history=history, profiles_dir=REPO_PROFILES)
    assert brief["deterministic_pick"]["family"] == "sparse"
    assert "available_families" in brief
    assert "schema_bounds" in brief
    assert brief["last_profile"] is not None


def test_recent_fitness_by_family(tmp_path: Path):
    write_profile_atomic(load_seed(REPO_PROFILES, "balanced"), runtime_dir=tmp_path)
    write_profile_atomic(load_seed(REPO_PROFILES, "sparse"), runtime_dir=tmp_path)
    append_history_event(tmp_path, "score", {"score": 0.8, "profile_id": "seed-balanced-default"})
    append_history_event(tmp_path, "score", {"score": -0.2, "profile_id": "seed-sparse-still-room"})
    fitness = recent_fitness_by_family(read_history_tail(tmp_path))
    assert fitness == {"balanced": 0.8, "sparse": -0.2}
