"""Tests for CV remap (cv6_main_mix_vca + cv7_glitch_trigger) and the
chord-pulse correlation injected into the ESP32 lighting sync.

Hardware patch this matches:
- ES-9 CV6 -> Intellijel Quad VCA CV1 (normalled to VCAs 2-4) -> main mix L/R volume
- ES-9 CV7 -> O&C logic gate -> pink-noise gate -> SWN dispersion_pattern (glitch spice)
"""
from __future__ import annotations

from audio.lisbon_swn_camera_bridge import (
    CV_LABELS,
    GLITCH_TRIGGER_CV_INDEX,
    HumanAwareSwnMapper,
    LisbonSwnMapper,
    PersonScene,
)
from lighting.lisbon_esp32_soundscape_sync import (
    _chord_pulse_period_ms,
    state_from_soundscape_status,
)


def _scene(people=0, activity=0.0, movement=0.0, near=0.0, mean_dist=0.0, count_norm=0.0) -> PersonScene:
    return PersonScene(
        people_count=people, tracks=[], centroid_x=0.5, centroid_y=0.5, spread_x=0.0,
        nearest_distance=near, mean_distance=mean_dist, movement=movement, activity=activity,
        count_norm=count_norm,
    )


def test_cv_labels_match_new_routing():
    """CV map locked to the Lisbon physical patch as of the Quad VCA install."""
    assert CV_LABELS[0] == "cv1_voice1_1v_oct"
    assert CV_LABELS[1] == "cv2_voice2_1v_oct"
    assert CV_LABELS[2] == "cv3_voice3_1v_oct"
    assert CV_LABELS[3] == "cv4_wavetable_browse"
    assert CV_LABELS[4] == "cv5_dispersion"
    assert CV_LABELS[5] == "cv6_main_mix_vca"
    assert CV_LABELS[6] == "cv7_glitch_trigger"
    assert CV_LABELS[7] == "cv8_depth"
    assert GLITCH_TRIGGER_CV_INDEX == 6


def test_main_mix_vca_baseline_when_room_empty():
    """No people / no activity should leave the mix near the empty floor.

    Live tuning 6/3: widened swing 0.10..0.95 of max_cv (was 0.60..0.90)
    so the modulation is unambiguous on the hardware Quad VCA past the
    LEVEL pot bias / exponential response curve.
    """
    mapper = HumanAwareSwnMapper(max_cv=0.30, smoothing_hz=100.0)
    # Drive enough steps for the slew to converge.
    for _ in range(80):
        cv = mapper.step_scene(_scene(), dt=0.05)
    # CV6 is index 5. Empty room: people=0, mean_d=0, activity=0 -> presence=0,
    # mix_target = 0.00 * max_cv = 0.00 (room goes silent when empty).
    assert cv[5] <= 0.005, f"empty mix should be near silence, got {cv[5]:.3f}"


def test_main_mix_vca_swells_with_presence():
    """A busy room should push the mix VCA higher than an empty one."""
    mapper = HumanAwareSwnMapper(max_cv=0.30, smoothing_hz=100.0)
    # Empty
    for _ in range(80):
        empty_cv = mapper.step_scene(_scene(), dt=0.05)
    # Reset for fair comparison
    mapper2 = HumanAwareSwnMapper(max_cv=0.30, smoothing_hz=100.0)
    busy_scene = _scene(people=3, activity=0.7, movement=0.5, near=0.6, mean_dist=0.4, count_norm=0.6)
    for _ in range(80):
        busy_cv = mapper2.step_scene(busy_scene, dt=0.05)
    assert busy_cv[5] > empty_cv[5], f"busy mix {busy_cv[5]:.3f} should exceed empty {empty_cv[5]:.3f}"


def test_glitch_trigger_silent_when_room_still():
    """Stillness should keep CV7 fully closed — no random pink-noise glitches."""
    mapper = HumanAwareSwnMapper(max_cv=0.30, smoothing_hz=100.0)
    for _ in range(80):
        cv = mapper.step_scene(_scene(movement=0.0, activity=0.0), dt=0.05)
    assert cv[6] == 0.0, f"still room should fully gate glitch, got {cv[6]:.3f}"


def test_glitch_trigger_opens_on_movement():
    """Real movement should open the glitch gate as spice."""
    mapper = HumanAwareSwnMapper(max_cv=0.30, smoothing_hz=100.0)
    for _ in range(40):
        cv = mapper.step_scene(_scene(people=2, movement=0.6, activity=0.5), dt=0.05)
    assert cv[6] > 0.05, f"movement should open glitch gate, got {cv[6]:.3f}"


def test_aggregate_mapper_uses_new_cv_semantics():
    """Aggregate (no-people) mode also gets the new mix VCA + glitch trigger semantics."""
    mapper = LisbonSwnMapper(max_cv=0.30, smoothing_hz=100.0)
    for _ in range(40):
        cv = mapper.step(brightness=0.6, motion=0.4, centroid_x=0.5, centroid_y=0.5, dt=0.05)
    # CV6 = main mix VCA. Aggregate mode mix_target = 0.10 + 0.85*0.495 = ~0.521,
    # *max_cv 0.30 = ~0.156. Allow band.
    assert 0.12 <= cv[5] <= 0.20, f"aggregate mix VCA out of band: {cv[5]:.3f}"
    # CV7 = glitch trigger, motion=0.4 should crack it open
    assert cv[6] > 0.0


# --- Chord pulse correlation (ESP32 lighting layer) ---

def test_chord_pulse_none_when_no_chord_block():
    assert _chord_pulse_period_ms(None) is None
    assert _chord_pulse_period_ms({}) is None
    assert _chord_pulse_period_ms({"voicing": "open_fifth"}) is None  # no root


def test_chord_pulse_slow_for_low_root():
    """Low root (D2 ~ 36) should give a slow breath ~750ms."""
    ms = _chord_pulse_period_ms({"root_semitones": 36.0})
    assert ms is not None and 700 <= ms <= 800


def test_chord_pulse_faster_for_high_root():
    """Higher root (A4 ~ 57) should breathe faster but still slow."""
    ms = _chord_pulse_period_ms({"root_semitones": 57.0})
    assert ms is not None and ms < _chord_pulse_period_ms({"root_semitones": 36.0})  # type: ignore


def test_chord_pulse_clamps_to_breathing_band():
    """Extreme roots should not push pulse outside the breathing band."""
    very_low = _chord_pulse_period_ms({"root_semitones": 0.0})
    very_high = _chord_pulse_period_ms({"root_semitones": 90.0})
    assert very_low is not None and 320 <= very_low <= 960
    assert very_high is not None and 320 <= very_high <= 960


def test_chord_pulse_overrides_audio_chase_in_drone_mode():
    """When a chord block is present, drone-mode chase_ms blends toward chord pulse."""
    # Build a status that lands in audio drone mode (mode 1, audio present, mid energy).
    status = {
        "ok": True,
        "max_cv": 0.30,
        "audio_input": {
            "stereo_rms": 0.08,
            "stereo_peak": 0.20,
            "dominant_frequency_hz": 90.0,
            "low_band_ratio": 0.85,  # bassy
            "high_band_ratio": 0.02,
            "mid_band_ratio": 0.05,
            "spectral_centroid_hz": 200.0,
            "glitch_score": 0.05,
            "transient": 0.05,
            "high_freq_ratio": 0.02,
        },
        "cv": {"cv4_wavetable_browse": 0.05, "cv5_dispersion": 0.04, "cv6_main_mix_vca": 0.18, "cv7_glitch_trigger": 0.0, "cv8_depth": 0.05},
        "chord": {"root_semitones": 36.0, "voicing": "open_fifth", "voice_offsets": [0.0, 7.0, 12.0]},
    }
    state = state_from_soundscape_status(status)
    assert state.mode == "1", f"expected drone mode, got {state.mode}"
    # Chord pulse at root 36 is ~747ms; without chord blend the drone params return chase~96.
    # With 50/50 blend we should land between the two -> roughly 400-500ms.
    assert state.chase_ms is not None and state.chase_ms > 200, f"chord pulse should slow chase, got {state.chase_ms}"
    assert "chord_pulse" in state.reason
