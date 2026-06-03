"""Tests for the chord voicing layer.

Schema bounds, palette resolution, profile seed validation, and the
fall-back-to-historical-default behavior in both SWN mappers.
"""
from __future__ import annotations

import json
import math
from pathlib import Path

import pytest

from audio.chord_palette import (
    ALLOWED_VOICINGS,
    DEFAULT_PITCH_WANDER,
    DEFAULT_ROOT_SEMITONES,
    DEFAULT_SMOOTHING_HZ,
    VOICINGS,
    resolve_chord,
)
from audio.heuristic_schema import BOUNDS, validate
from audio.lisbon_swn_camera_bridge import (
    HumanAwareSwnMapper,
    LisbonSwnMapper,
    PersonScene,
    PersonTrack,
)


REPO_PROFILES = Path(__file__).resolve().parents[1] / "audio" / "profiles"


def test_voicings_have_three_voices():
    for name, offsets in VOICINGS.items():
        assert len(offsets) == 3, f"{name}: expected 3 voice offsets, got {len(offsets)}"


def test_resolve_chord_defaults():
    res = resolve_chord(None)
    assert res["root_semitones"] == DEFAULT_ROOT_SEMITONES
    assert res["voice_offsets"] == VOICINGS["open_fifth"]
    assert res["smoothing_hz"] == DEFAULT_SMOOTHING_HZ
    assert res["pitch_wander_scale"] == DEFAULT_PITCH_WANDER


def test_resolve_chord_named_voicing():
    res = resolve_chord({"voicing": "minor_triad", "root_semitones": 33.0})
    assert res["voicing"] == "minor_triad"
    assert res["voice_offsets"] == VOICINGS["minor_triad"]
    assert res["root_semitones"] == 33.0


def test_resolve_chord_unknown_voicing_falls_back():
    res = resolve_chord({"voicing": "fictional_chord"})
    assert res["voicing"] is None
    assert res["voice_offsets"] == VOICINGS["open_fifth"]


def test_resolve_chord_explicit_offsets_override_voicing():
    res = resolve_chord({
        "voicing": "open_fifth",
        "voice_1_semitones": 0.0,
        "voice_2_semitones": 4.0,  # major third
        "voice_3_semitones": 10.0,
    })
    assert res["voice_offsets"] == (0.0, 4.0, 10.0)


def test_schema_includes_chord_bounds():
    for key in [
        "chord.root_semitones",
        "chord.voice_1_semitones",
        "chord.voice_2_semitones",
        "chord.voice_3_semitones",
        "chord.smoothing_hz",
        "chord.pitch_wander_scale",
    ]:
        assert key in BOUNDS


def test_all_seed_profiles_have_valid_chords():
    for fname in REPO_PROFILES.glob("*.json"):
        profile = json.loads(fname.read_text())
        chord = profile.get("chord")
        assert chord is not None, f"{fname.name} missing chord block"
        if "voicing" in chord:
            assert chord["voicing"] in ALLOWED_VOICINGS, f"{fname.name} has unknown voicing"
        assert validate(profile) == [], f"{fname.name} validation errors: {validate(profile)}"


def _empty_scene() -> PersonScene:
    return PersonScene(
        people_count=0, tracks=[], centroid_x=0.5, centroid_y=0.5, spread_x=0.0,
        nearest_distance=0.0, mean_distance=0.0, movement=0.0, activity=0.0, count_norm=0.0,
    )


def test_human_mapper_falls_back_to_open_fifth_without_chord():
    """No chord set → mapper uses historical [0, 7, 12] open-fifth."""
    mapper = HumanAwareSwnMapper(max_cv=0.25, smoothing_hz=8.0)
    cv = mapper.step_scene(_empty_scene(), dt=0.0)
    semitone = 1.0 / 120.0
    # Voice 1 ~= root (small variance from pitch_wander only)
    assert math.isclose(cv[0], 0.0, abs_tol=0.02)
    # Voice 2 ~= 7 semitones up
    assert math.isclose(cv[1], 7 * semitone, abs_tol=0.02)
    # Voice 3 ~= 12 semitones up
    assert math.isclose(cv[2], 12 * semitone, abs_tol=0.02)


def test_human_mapper_uses_chord_when_set():
    """Setting a minor triad chord should shift CV outputs accordingly."""
    mapper = HumanAwareSwnMapper(max_cv=0.30, smoothing_hz=100.0)  # near-instant slew
    chord = resolve_chord({"voicing": "minor_triad", "root_semitones": 36.0})
    mapper.set_chord(chord)
    # Run a few steps so the slew converges
    for _ in range(50):
        cv = mapper.step_scene(_empty_scene(), dt=0.05)
    semitone = 1.0 / 120.0
    # root_semi=0 (36 - 36); offsets are (0, 3, 7) for minor_triad
    assert math.isclose(cv[0], 0.0, abs_tol=0.02)
    assert math.isclose(cv[1], 3 * semitone, abs_tol=0.02)
    assert math.isclose(cv[2], 7 * semitone, abs_tol=0.02)


def test_aggregate_mapper_uses_chord():
    """Same test for the older LisbonSwnMapper that the bridge uses for non-people vision mode."""
    mapper = LisbonSwnMapper(max_cv=0.30, smoothing_hz=100.0)
    chord = resolve_chord({"voicing": "quartal", "root_semitones": 36.0})
    mapper.set_chord(chord)
    for _ in range(50):
        cv = mapper.step(brightness=0.0, motion=0.0, centroid_x=0.5, centroid_y=0.5, dt=0.05)
    semitone = 1.0 / 120.0
    # quartal = (0, 5, 10)
    assert math.isclose(cv[0], 0.0, abs_tol=0.02)
    assert math.isclose(cv[1], 5 * semitone, abs_tol=0.02)
    assert math.isclose(cv[2], 10 * semitone, abs_tol=0.02)


def test_mapper_chord_can_be_cleared():
    mapper = HumanAwareSwnMapper(max_cv=0.30, smoothing_hz=100.0)
    mapper.set_chord(resolve_chord({"voicing": "minor_triad"}))
    for _ in range(20):
        mapper.step_scene(_empty_scene(), dt=0.05)
    mapper.set_chord(None)
    for _ in range(50):
        cv = mapper.step_scene(_empty_scene(), dt=0.05)
    semitone = 1.0 / 120.0
    # Back to open-fifth
    assert math.isclose(cv[1], 7 * semitone, abs_tol=0.02)


def test_chord_bounds_are_clamped_on_write(tmp_path: Path):
    """Out-of-range chord values get clamped, not rejected."""
    from audio.heuristic_schema import write_profile_atomic
    bad = {
        "schema": "lisbon.heuristic_profile.v1",
        "profile_id": "bad-chord",
        "chord": {
            "root_semitones": 999.0,
            "voice_1_semitones": -999.0,
            "voice_3_semitones": 999.0,
            "smoothing_hz": -5.0,
            "pitch_wander_scale": 50.0,
        },
    }
    result = write_profile_atomic(bad, runtime_dir=tmp_path)
    written = json.loads(result.path.read_text())
    assert written["chord"]["root_semitones"] == BOUNDS["chord.root_semitones"][1]
    assert written["chord"]["voice_1_semitones"] == BOUNDS["chord.voice_1_semitones"][0]
    assert written["chord"]["voice_3_semitones"] == BOUNDS["chord.voice_3_semitones"][1]
    assert written["chord"]["smoothing_hz"] == BOUNDS["chord.smoothing_hz"][0]
    assert written["chord"]["pitch_wander_scale"] == BOUNDS["chord.pitch_wander_scale"][1]
