"""Tests for glacial autonomous chord drift.

Two slow LFOs perturb root + voice offsets so the chord is never frozen
even when no reviewer profile arrives. Bounded by amplitude constants;
voicing identity preserved.
"""
from __future__ import annotations

import math

from audio.chord_palette import (
    apply_chord_drift,
    resolve_chord,
    DRIFT_ROOT_AMPL_SEMI,
    DRIFT_OFFSET_AMPL_SEMI,
    DRIFT_ROOT_PERIOD_SEC,
    DRIFT_OFFSET_PERIOD_SEC,
)


def test_drift_zero_phase_is_identity():
    chord = resolve_chord({"voicing": "open_fifth"})
    drifted = apply_chord_drift(chord, drift_phase_seconds=0.0)
    assert math.isclose(drifted["root_semitones"], chord["root_semitones"])
    assert drifted["voice_offsets"] == chord["voice_offsets"]


def test_drift_quarter_root_period_is_max_root():
    chord = resolve_chord({"voicing": "open_fifth", "root_semitones": 36.0})
    # sin(pi/2) = 1 -> root drifts by +DRIFT_ROOT_AMPL_SEMI
    drifted = apply_chord_drift(chord, drift_phase_seconds=DRIFT_ROOT_PERIOD_SEC / 4.0)
    assert math.isclose(drifted["root_semitones"], 36.0 + DRIFT_ROOT_AMPL_SEMI, abs_tol=1e-6)


def test_drift_voice2_voice3_breathe_opposite_phase():
    chord = resolve_chord({"voicing": "open_fifth", "root_semitones": 36.0})  # (0,7,12)
    # Quarter offset period -> sin = 1
    drifted = apply_chord_drift(chord, drift_phase_seconds=DRIFT_OFFSET_PERIOD_SEC / 4.0)
    v1, v2, v3 = drifted["voice_offsets"]
    # Voice 1 anchored
    assert math.isclose(v1, 0.0)
    # Voice 2 pushed up by ampl
    assert math.isclose(v2, 7.0 + DRIFT_OFFSET_AMPL_SEMI, abs_tol=1e-6)
    # Voice 3 pulled down by ampl (opposite phase)
    assert math.isclose(v3, 12.0 - DRIFT_OFFSET_AMPL_SEMI, abs_tol=1e-6)


def test_drift_bounded_by_amplitudes():
    """For any phase, drift never exceeds the configured amplitudes."""
    chord = resolve_chord({"voicing": "open_fifth", "root_semitones": 36.0})
    base_root = 36.0
    base_v2 = 7.0
    base_v3 = 12.0
    for phase in [0, 100, 500, 1000, 2000, 5000, 13579]:
        drifted = apply_chord_drift(chord, drift_phase_seconds=phase)
        assert abs(drifted["root_semitones"] - base_root) <= DRIFT_ROOT_AMPL_SEMI + 1e-9
        v1, v2, v3 = drifted["voice_offsets"]
        assert v1 == 0.0  # never moves
        assert abs(v2 - base_v2) <= DRIFT_OFFSET_AMPL_SEMI + 1e-9
        assert abs(v3 - base_v3) <= DRIFT_OFFSET_AMPL_SEMI + 1e-9


def test_drift_returns_new_dict_does_not_mutate():
    chord = resolve_chord({"voicing": "minor_triad"})
    original_root = chord["root_semitones"]
    original_offsets = chord["voice_offsets"]
    apply_chord_drift(chord, drift_phase_seconds=123.0)
    assert chord["root_semitones"] == original_root
    assert chord["voice_offsets"] == original_offsets


def test_drift_preserves_voicing_label_and_metadata():
    chord = resolve_chord({"voicing": "quartal", "smoothing_hz": 0.7, "transition_seconds": 45})
    drifted = apply_chord_drift(chord, drift_phase_seconds=200.0)
    assert drifted["voicing"] == "quartal"
    assert drifted["smoothing_hz"] == 0.7
    assert drifted["transition_seconds"] == 45.0


def test_drift_root_and_offset_periods_independent():
    """Root and voice drift should not phase-lock — they use different periods."""
    chord = resolve_chord({"voicing": "open_fifth"})
    # At a phase where one is at zero crossing but the other isn't
    phase = DRIFT_ROOT_PERIOD_SEC / 2.0  # root sin = 0
    drifted = apply_chord_drift(chord, drift_phase_seconds=phase)
    assert math.isclose(drifted["root_semitones"], chord["root_semitones"], abs_tol=1e-9)
    # Voice 2 should still have moved because offset period is different
    voice_off_phase = (phase / DRIFT_OFFSET_PERIOD_SEC) * 2.0 * math.pi
    expected_v2 = 7.0 + DRIFT_OFFSET_AMPL_SEMI * math.sin(voice_off_phase)
    assert math.isclose(drifted["voice_offsets"][1], expected_v2, abs_tol=1e-6)
