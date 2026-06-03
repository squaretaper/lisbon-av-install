"""Tests for chord transitions (slow modulation between voicings)."""
from __future__ import annotations

import math
import time

from audio.chord_palette import (
    interpolate_chord,
    resolve_chord,
)
from audio.lisbon_swn_camera_bridge import (
    HumanAwareSwnMapper,
    PersonScene,
)


def _empty_scene() -> PersonScene:
    return PersonScene(
        people_count=0, tracks=[], centroid_x=0.5, centroid_y=0.5, spread_x=0.0,
        nearest_distance=0.0, mean_distance=0.0, movement=0.0, activity=0.0, count_norm=0.0,
    )


def test_interpolate_returns_to_chord_when_no_from():
    target = resolve_chord({"voicing": "minor_triad", "transition_seconds": 30.0})
    result = interpolate_chord(None, target, elapsed_seconds=5.0)
    assert result is target


def test_interpolate_returns_to_chord_when_duration_zero():
    a = resolve_chord({"voicing": "open_fifth", "transition_seconds": 0.0})
    b = resolve_chord({"voicing": "minor_triad", "transition_seconds": 0.0})
    result = interpolate_chord(a, b, elapsed_seconds=15.0)
    assert result is b


def test_interpolate_returns_to_chord_when_elapsed_past_duration():
    a = resolve_chord({"voicing": "open_fifth", "transition_seconds": 10.0})
    b = resolve_chord({"voicing": "minor_triad", "transition_seconds": 10.0})
    result = interpolate_chord(a, b, elapsed_seconds=999.0)
    assert result is b


def test_interpolate_midway_crossfades_voice_offsets():
    a = resolve_chord({"voicing": "open_fifth", "transition_seconds": 10.0})  # (0,7,12)
    b = resolve_chord({"voicing": "minor_triad", "transition_seconds": 10.0})  # (0,3,7)
    midway = interpolate_chord(a, b, elapsed_seconds=5.0)  # smoothstep(0.5) = 0.5
    # Voice 1 stays at 0
    assert math.isclose(midway["voice_offsets"][0], 0.0)
    # Voice 2: linear 5 (midpoint between 7 and 3), smoothstep gives same at 0.5
    assert math.isclose(midway["voice_offsets"][1], 5.0)
    # Voice 3: midpoint between 12 and 7 = 9.5
    assert math.isclose(midway["voice_offsets"][2], 9.5)
    # Progress tag present for debug surfaces
    assert math.isclose(midway["_transition_progress"], 0.5)


def test_interpolate_smoothstep_eases_in_and_out():
    a = resolve_chord({"voicing": "grounding", "transition_seconds": 10.0})  # (0,0,0)
    b = resolve_chord({"voicing": "open_fifth", "transition_seconds": 10.0})  # (0,7,12)
    # At t=0.1 (early), smoothstep(0.1) = 0.028; voice 3 = 0.028*12 ≈ 0.336
    early = interpolate_chord(a, b, elapsed_seconds=1.0)
    assert early["voice_offsets"][2] < 1.0  # not yet at 1.2 (linear would be)
    # At t=0.9 (late), smoothstep(0.9) = 0.972; voice 3 ≈ 11.66
    late = interpolate_chord(a, b, elapsed_seconds=9.0)
    assert late["voice_offsets"][2] > 11.0


def test_mapper_set_chord_starts_transition():
    """When set_chord receives a different chord, _active_chord interpolates."""
    mapper = HumanAwareSwnMapper(max_cv=0.30, smoothing_hz=100.0)
    a = resolve_chord({"voicing": "open_fifth", "transition_seconds": 10.0})
    mapper.set_chord(a)
    # Step once to let slew catch up to a
    for _ in range(20):
        mapper.step_scene(_empty_scene(), dt=0.05)
    # Now switch chord; immediately, the active chord should still be a-like
    b = resolve_chord({"voicing": "minor_triad", "transition_seconds": 10.0})
    mapper.set_chord(b)
    # Override the monotonic clock for deterministic timing
    base = mapper._chord_set_at
    mapper._chord_now = lambda: base + 0.0  # zero elapsed
    mapper._drift_start = base  # neutralize glacial drift for this test
    active = mapper._active_chord()
    assert active is not None
    # Just-after-set: voice_offsets should equal a (drift phase is 0 -> sin=0)
    assert math.isclose(active["voice_offsets"][1], 7.0, abs_tol=0.1)

    # Skip halfway. Drift advances too — re-anchor _drift_start so the test
    # measures the transition crossfade, not the LFO position.
    mapper._chord_now = lambda: base + 5.0
    mapper._drift_start = base + 5.0
    active = mapper._active_chord()
    # Voice 2 mid-way between 7 (open_fifth) and 3 (minor_triad) = 5
    assert math.isclose(active["voice_offsets"][1], 5.0, abs_tol=0.1)

    # Skip past end. Same re-anchor pattern.
    mapper._chord_now = lambda: base + 999.0
    mapper._drift_start = base + 999.0
    active = mapper._active_chord()
    # Reached target
    assert math.isclose(active["voice_offsets"][1], 3.0, abs_tol=0.01)


def test_mapper_identical_chord_does_not_restart_transition():
    """Re-applying the same chord should not snapshot a new previous or reset the timer."""
    mapper = HumanAwareSwnMapper(max_cv=0.30, smoothing_hz=100.0)
    a = resolve_chord({"voicing": "minor_triad", "transition_seconds": 30.0})
    mapper.set_chord(a)
    first_set_at = mapper._chord_set_at
    time.sleep(0.02)
    mapper.set_chord(a)  # same chord
    assert mapper._chord_set_at == first_set_at, "identical chord should not bump timer"
    assert mapper._chord_previous is None
