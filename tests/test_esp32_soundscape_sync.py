import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from lighting.lisbon_esp32_soundscape_sync import (
    LightState,
    build_arg_parser,
    commands_for_transition,
    status_age_ms,
    state_after_commands,
    state_from_soundscape_status,
)


def test_light_bridge_defaults_are_low_latency_but_bounded():
    args = build_arg_parser().parse_args([])

    assert args.interval <= 0.025
    assert args.serial_delay <= 0.001
    # 6/4: bumped 6 -> 12 so strobe brightness 255 can land from any chase
    # baseline in a single status update (delta of up to 160 brightness
    # units = 10 +/- commands). Still bounded so a runaway target can't
    # spam the serial port indefinitely.
    assert args.max_brightness_steps <= 12
    assert args.max_param_steps <= 6


def status_template(**overrides):
    status = {
        "ok": True,
        "audio_input": {
            "input_1_rms": 0.0,
            "input_2_rms": 0.0,
            "input_1_peak": 0.0,
            "input_2_peak": 0.0,
            "stereo_rms": 0.0,
            "stereo_peak": 0.0,
            "freq_hz": 0.0,
            "zero_crossing_hz": 0.0,
            "high_freq_ratio": 0.0,
            "transient": 0.0,
            "glitch_score": 0.0,
        },
        "cv": {
            "cv4_wavetable_browse": 0.04,
            "cv5_dispersion": 0.02,
            "cv6_dispersion_pattern": 0.02,
            "cv7_movement_gate": 0.03,
            "cv8_depth": 0.03,
        },
        "features": {"motion": 0.001, "brightness": 0.45},
        "person_scene": {
            "people_count": 0,
            "count_norm": 0.0,
            "activity": 0.0,
            "movement": 0.0,
            "nearest_distance": 0.0,
            "spread_x": 0.0,
        },
    }
    status.update(overrides)
    return status


def test_status_age_ms_uses_status_timestamp_for_latency_logging():
    status = status_template(timestamp=1000.125)

    assert status_age_ms(status, observed_at=1000.200) == 75


def test_status_age_ms_missing_timestamp_returns_none():
    status = status_template()

    assert status_age_ms(status, observed_at=1000.200) is None


def test_empty_room_maps_to_low_dystopian_breath():
    state = state_from_soundscape_status(status_template())

    assert state.mode == "4"
    assert 32 <= state.brightness <= 80
    assert "empty" in state.reason


def test_close_single_person_maps_to_chase_and_brighter_output():
    status = status_template(
        person_scene={
            "people_count": 1,
            "count_norm": 0.25,
            "activity": 0.22,
            "movement": 0.04,
            "nearest_distance": 0.74,
            "spread_x": 0.0,
        }
    )

    state = state_from_soundscape_status(status)

    assert state.mode == "1"
    assert state.brightness >= 80
    assert "near" in state.reason


def test_audio_frequency_maps_directly_to_chase_mode():
    status = status_template(
        audio_input={
            "input_1_rms": 0.11,
            "input_2_rms": 0.10,
            "input_1_peak": 0.2,
            "input_2_peak": 0.18,
            "stereo_rms": 0.105,
            "stereo_peak": 0.2,
            "freq_hz": 2600.0,
            "zero_crossing_hz": 2600.0,
            "high_freq_ratio": 0.32,
            "transient": 0.05,
            "glitch_score": 0.12,
        }
    )

    state = state_from_soundscape_status(status)

    assert state.mode == "1"
    assert state.brightness >= 80
    assert "freq" in state.reason


def test_audio_glitch_score_overrides_people_activity_to_glitch_mode():
    status = status_template(
        audio_input={
            "input_1_rms": 0.06,
            "input_2_rms": 0.05,
            "input_1_peak": 0.8,
            "input_2_peak": 0.7,
            "stereo_rms": 0.055,
            "stereo_peak": 0.8,
            "freq_hz": 900.0,
            "zero_crossing_hz": 900.0,
            "high_freq_ratio": 0.7,
            "transient": 0.9,
            "glitch_score": 0.86,
        },
        person_scene={
            "people_count": 1,
            "count_norm": 0.25,
            "activity": 0.2,
            "movement": 0.04,
            "nearest_distance": 0.55,
            "spread_x": 0.0,
        },
    )

    state = state_from_soundscape_status(status)

    assert state.mode == "2"
    assert state.brightness >= 112
    assert "glitch" in state.reason


def test_low_drone_audio_maps_to_chasing_breathing_pulse_not_people_fallback():
    status = status_template(
        audio_input={
            "input_1_rms": 0.12,
            "input_2_rms": 0.13,
            "input_1_peak": 0.22,
            "input_2_peak": 0.24,
            "stereo_rms": 0.125,
            "stereo_peak": 0.24,
            "freq_hz": 188.0,
            "zero_crossing_hz": 188.0,
            "dominant_frequency_hz": 188.0,
            "spectral_centroid_hz": 240.0,
            "low_band_ratio": 0.82,
            "high_band_ratio": 0.02,
            "high_freq_ratio": 0.02,
            "transient": 0.0,
            "glitch_score": 0.01,
        },
        person_scene={
            "people_count": 3,
            "count_norm": 0.75,
            "activity": 0.4,
            "movement": 0.05,
            "nearest_distance": 0.7,
            "spread_x": 0.6,
        },
    )

    state = state_from_soundscape_status(status)

    assert state.mode == "1"
    assert 96 <= state.brightness <= 176
    assert state.chase_ms is not None
    assert state.pulse_depth is not None
    assert "drone chase" in state.reason


def test_faint_low_drone_still_chases_but_allows_near_black_intensity():
    status = status_template(
        audio_input={
            "input_1_rms": 0.014,
            "input_2_rms": 0.016,
            "input_1_peak": 0.026,
            "input_2_peak": 0.030,
            "stereo_rms": 0.015,
            "stereo_peak": 0.030,
            "freq_hz": 96.0,
            "zero_crossing_hz": 96.0,
            "dominant_frequency_hz": 96.0,
            "spectral_centroid_hz": 150.0,
            "low_band_ratio": 0.92,
            "mid_band_ratio": 0.07,
            "high_band_ratio": 0.01,
            "high_freq_ratio": 0.01,
            "transient": 0.0,
            "glitch_score": 0.0,
        }
    )

    state = state_from_soundscape_status(status)

    assert state.mode == "1"
    assert 16 <= state.brightness <= 64
    assert state.chase_ms is not None
    assert state.pulse_depth is not None
    assert "drone chase" in state.reason


def test_drone_chase_speed_and_pulse_track_frequency_and_energy():
    low_status = status_template(
        audio_input={
            "input_1_rms": 0.10,
            "input_2_rms": 0.10,
            "stereo_rms": 0.10,
            "stereo_peak": 0.18,
            "freq_hz": 110.0,
            "dominant_frequency_hz": 110.0,
            "spectral_centroid_hz": 180.0,
            "low_band_ratio": 0.94,
            "mid_band_ratio": 0.05,
            "high_band_ratio": 0.01,
            "high_freq_ratio": 0.01,
            "transient": 0.0,
            "glitch_score": 0.0,
        }
    )
    higher_status = status_template(
        audio_input={
            "input_1_rms": 0.15,
            "input_2_rms": 0.15,
            "stereo_rms": 0.15,
            "stereo_peak": 0.25,
            "freq_hz": 700.0,
            "dominant_frequency_hz": 700.0,
            "spectral_centroid_hz": 780.0,
            "low_band_ratio": 0.55,
            "mid_band_ratio": 0.43,
            "high_band_ratio": 0.02,
            "high_freq_ratio": 0.02,
            "transient": 0.0,
            "glitch_score": 0.0,
        }
    )

    low = state_from_soundscape_status(low_status)
    higher = state_from_soundscape_status(higher_status)

    assert low.mode == higher.mode == "1"
    assert low.chase_ms is not None and higher.chase_ms is not None
    assert higher.chase_ms < low.chase_ms
    assert low.pulse_depth is not None and higher.pulse_depth is not None
    assert higher.pulse_depth >= low.pulse_depth
    assert "speed=" in higher.reason


def test_lower_drone_frequencies_move_slower_and_spread_packet_crossings():
    low_status = status_template(
        audio_input={
            "input_1_rms": 0.12,
            "input_2_rms": 0.12,
            "stereo_rms": 0.12,
            "stereo_peak": 0.22,
            "freq_hz": 96.0,
            "dominant_frequency_hz": 96.0,
            "spectral_centroid_hz": 160.0,
            "low_band_ratio": 0.92,
            "mid_band_ratio": 0.07,
            "high_band_ratio": 0.01,
            "high_freq_ratio": 0.01,
            "transient": 0.0,
            "glitch_score": 0.0,
        }
    )
    mid_status = status_template(
        audio_input={
            "input_1_rms": 0.12,
            "input_2_rms": 0.12,
            "stereo_rms": 0.12,
            "stereo_peak": 0.22,
            "freq_hz": 375.0,
            "dominant_frequency_hz": 375.0,
            "spectral_centroid_hz": 530.0,
            "low_band_ratio": 0.75,
            "mid_band_ratio": 0.23,
            "high_band_ratio": 0.02,
            "high_freq_ratio": 0.02,
            "transient": 0.0,
            "glitch_score": 0.0,
        }
    )

    low = state_from_soundscape_status(low_status)
    mid = state_from_soundscape_status(mid_status)

    assert low.mode == mid.mode == "1"
    assert low.chase_ms is not None and mid.chase_ms is not None
    assert low.chase_ms >= 120
    assert low.chase_ms > mid.chase_ms
    assert low.packet_span is not None and mid.packet_span is not None
    assert low.packet_span > mid.packet_span
    assert "span=" in low.reason


def test_live_calibrated_375hz_drone_moves_as_slow_crossing_packets():
    status = status_template(
        audio_input={
            "input_1_rms": 0.11,
            "input_2_rms": 0.16,
            "stereo_rms": 0.14,
            "stereo_peak": 0.22,
            "freq_hz": 375.0,
            "dominant_frequency_hz": 375.0,
            "spectral_centroid_hz": 528.0,
            "low_band_ratio": 0.75,
            "mid_band_ratio": 0.23,
            "high_band_ratio": 0.012,
            "high_freq_ratio": 0.02,
            "transient": 0.0,
            "glitch_score": 0.05,
        }
    )

    state = state_from_soundscape_status(status)

    assert state.mode == "1"
    assert state.chase_ms is not None and state.chase_ms >= 100
    assert state.packet_span is not None and state.packet_span >= 28
    assert "span=" in state.reason


def test_commands_for_transition_adjust_chase_speed_pulse_and_packet_span_smoothly():
    current = LightState(mode="1", brightness=128, chase_ms=64, pulse_depth=32, packet_span=18, reason="current")
    target = LightState(mode="1", brightness=160, chase_ms=44, pulse_depth=64, packet_span=32, reason="target")

    commands = commands_for_transition(current, target, max_brightness_steps=2, max_param_steps=2)

    assert commands.count("+") == 2
    assert commands.count(">") == 2
    assert commands.count("]") == 2
    assert commands.count("}") == 2


def test_state_after_commands_tracks_limited_hardware_state_not_unreached_target():
    current = LightState(mode="1", brightness=128, chase_ms=64, pulse_depth=32, packet_span=18, reason="current")
    target = LightState(mode="1", brightness=176, chase_ms=36, pulse_depth=96, packet_span=34, reason="target")
    commands = ["+", ">", "]", "}"]

    applied = state_after_commands(current, commands, target)

    assert applied.brightness == 144
    assert applied.chase_ms == 60
    assert applied.pulse_depth == 40
    assert applied.packet_span == 20
    assert applied.reason == "target"


def test_state_after_commands_can_track_slow_drone_chase_above_legacy_cap():
    current = LightState(mode="1", brightness=128, chase_ms=88, pulse_depth=72, packet_span=30, reason="current")
    target = LightState(mode="1", brightness=128, chase_ms=104, pulse_depth=72, packet_span=30, reason="target")
    commands = ["<", "<", "<", "<"]

    applied = state_after_commands(current, commands, target)
    followup = commands_for_transition(applied, target, max_param_steps=6)

    assert applied.chase_ms == 104
    assert "<" not in followup


def test_low_drone_derivative_glitch_score_without_bright_content_stays_chase():
    status = status_template(
        audio_input={
            "input_1_rms": 0.11,
            "input_2_rms": 0.16,
            "stereo_rms": 0.14,
            "stereo_peak": 0.21,
            "freq_hz": 375.0,
            "dominant_frequency_hz": 375.0,
            "spectral_centroid_hz": 528.0,
            "low_band_ratio": 0.75,
            "mid_band_ratio": 0.23,
            "high_band_ratio": 0.012,
            "high_freq_ratio": 0.02,
            "transient": 0.0,
            "glitch_score": 0.27,
        }
    )

    state = state_from_soundscape_status(status)

    assert state.mode == "1"
    assert "drone chase" in state.reason


def test_low_drone_peak_transient_without_bright_content_stays_chase():
    status = status_template(
        audio_input={
            "input_1_rms": 0.08,
            "input_2_rms": 0.11,
            "stereo_rms": 0.10,
            "stereo_peak": 0.38,
            "freq_hz": 375.0,
            "dominant_frequency_hz": 375.0,
            "spectral_centroid_hz": 540.0,
            "low_band_ratio": 0.80,
            "mid_band_ratio": 0.18,
            "high_band_ratio": 0.01,
            "high_freq_ratio": 0.02,
            "transient": 0.57,
            "glitch_score": 0.30,
        }
    )

    state = state_from_soundscape_status(status)

    assert state.mode == "1"
    assert "drone chase" in state.reason


def test_high_band_glitch_burst_triggers_strobe_even_when_dominant_drone_remains():
    status = status_template(
        audio_input={
            "input_1_rms": 0.12,
            "input_2_rms": 0.12,
            "stereo_rms": 0.12,
            "stereo_peak": 0.21,
            "freq_hz": 188.0,
            "dominant_frequency_hz": 188.0,
            "spectral_centroid_hz": 1188.0,
            "low_band_ratio": 0.50,
            "mid_band_ratio": 0.31,
            "high_band_ratio": 0.185,
            "high_freq_ratio": 0.185,
            "transient": 0.0,
            "glitch_score": 0.09,
        }
    )

    state = state_from_soundscape_status(status)

    assert state.mode == "2"
    assert "strobe" in state.reason


def test_high_frequency_glitch_audio_maps_to_strobic_fault_mode():
    status = status_template(
        audio_input={
            "input_1_rms": 0.07,
            "input_2_rms": 0.08,
            "input_1_peak": 0.42,
            "input_2_peak": 0.45,
            "stereo_rms": 0.075,
            "stereo_peak": 0.45,
            "freq_hz": 3600.0,
            "zero_crossing_hz": 3600.0,
            "dominant_frequency_hz": 3600.0,
            "spectral_centroid_hz": 4200.0,
            "low_band_ratio": 0.04,
            "high_band_ratio": 0.46,
            "high_freq_ratio": 0.46,
            "transient": 0.18,
            "glitch_score": 0.22,
        },
        person_scene={
            "people_count": 0,
            "count_norm": 0.0,
            "activity": 0.0,
            "movement": 0.0,
            "nearest_distance": 0.0,
            "spread_x": 0.0,
        },
    )

    state = state_from_soundscape_status(status)

    assert state.mode == "2"
    assert state.brightness >= 208
    assert "strobe" in state.reason


def test_transient_score_field_from_audio_bridge_triggers_strobic_fault_mode():
    status = status_template(
        audio_input={
            "input_1_rms": 0.10,
            "input_2_rms": 0.11,
            "input_1_peak": 0.32,
            "input_2_peak": 0.36,
            "stereo_rms": 0.105,
            "stereo_peak": 0.36,
            "freq_hz": 750.0,
            "zero_crossing_hz": 750.0,
            "dominant_frequency_hz": 750.0,
            "spectral_centroid_hz": 1200.0,
            "low_band_ratio": 0.34,
            "mid_band_ratio": 0.58,
            "high_band_ratio": 0.08,
            "high_freq_ratio": 0.08,
            "transient_score": 0.72,
            "glitch_score": 0.10,
        },
    )

    state = state_from_soundscape_status(status)

    assert state.mode == "2"
    assert state.brightness >= 128
    assert "strobe" in state.reason


def test_live_calibrated_mid_high_glitch_peak_triggers_strobe_not_drone_chase():
    status = status_template(
        audio_input={
            "input_1_rms": 0.14,
            "input_2_rms": 0.15,
            "input_1_peak": 0.30,
            "input_2_peak": 0.33,
            "stereo_rms": 0.145,
            "stereo_peak": 0.33,
            "freq_hz": 750.0,
            "zero_crossing_hz": 750.0,
            "dominant_frequency_hz": 750.0,
            "spectral_centroid_hz": 720.0,
            "low_band_ratio": 0.40,
            "mid_band_ratio": 0.56,
            "high_band_ratio": 0.04,
            "high_freq_ratio": 0.04,
            "transient_score": 0.05,
            "glitch_score": 0.22,
        },
    )

    state = state_from_soundscape_status(status)

    assert state.mode == "2"
    assert "strobe" in state.reason


def test_soundscape_cv_glitch_proxy_overrides_group_when_audio_return_is_silent():
    status = status_template(
        audio_input={
            "input_1_rms": 0.0,
            "input_2_rms": 0.0,
            "input_1_peak": 0.0,
            "input_2_peak": 0.0,
            "stereo_rms": 0.0,
            "stereo_peak": 0.0,
            "freq_hz": 0.0,
            "zero_crossing_hz": 0.0,
            "high_freq_ratio": 0.0,
            "transient": 0.0,
            "glitch_score": 0.0,
        },
        cv={
            "cv4_wavetable_browse": 0.12,
            "cv5_dispersion": 0.16,
            "cv6_dispersion_pattern": 0.14,
            "cv7_movement_gate": 0.12,
            "cv8_depth": 0.17,
        },
        person_scene={
            "people_count": 2,
            "count_norm": 0.5,
            "activity": 0.25,
            "movement": 0.08,
            "nearest_distance": 0.42,
            "spread_x": 0.44,
        },
    )

    state = state_from_soundscape_status(status)

    assert state.mode == "2"
    assert state.brightness >= 112
    # 6/4: CV7 glitch_trigger >= 0.40 of max_cv (0.16 / 0.20 = 0.80 normalized)
    # now fires the PRIORITY 1 direct strobe path. The legacy "soundscape glitch"
    # path is reserved for the cv7 < 0.40 case where dispersion/depth/main_mix
    # together still cross 0.52 on the soundscape_glitch score.
    assert "cv7 glitch direct strobe" in state.reason


def test_soundscape_cv_frequency_proxy_maps_to_chase_when_audio_return_is_silent():
    status = status_template(
        audio_input={
            "input_1_rms": 0.0,
            "input_2_rms": 0.0,
            "input_1_peak": 0.0,
            "input_2_peak": 0.0,
            "stereo_rms": 0.0,
            "stereo_peak": 0.0,
            "freq_hz": 0.0,
            "zero_crossing_hz": 0.0,
            "high_freq_ratio": 0.0,
            "transient": 0.0,
            "glitch_score": 0.0,
        },
        cv={
            "cv4_wavetable_browse": 0.18,
            "cv5_dispersion": 0.03,
            "cv6_dispersion_pattern": 0.03,
            "cv7_movement_gate": 0.06,  # 6/4: kept below 0.40 of max_cv 0.20 (=0.30 normalized) so the new CV7 direct-strobe path does NOT trigger; this test asserts the chase fallback when browse is the dominant CV
            "cv8_depth": 0.04,
        },
    )

    state = state_from_soundscape_status(status)

    assert state.mode == "1"
    assert state.brightness >= 80
    assert "soundscape freq" in state.reason


def test_error_status_blackouts():
    state = state_from_soundscape_status(status_template(ok=False, error="camera stale"))

    assert state == LightState(mode="x", brightness=0, reason="status not ok")


def test_transition_commands_use_existing_dual_strip_protocol():
    current = LightState(mode="4", brightness=64, reason="old")
    target = LightState(mode="2", brightness=112, reason="new")

    assert commands_for_transition(current, target) == ["2", "+", "+", "+"]


def test_transition_limits_brightness_step_burst():
    current = LightState(mode="1", brightness=160, reason="old")
    target = LightState(mode="1", brightness=32, reason="new")

    assert commands_for_transition(current, target, max_brightness_steps=2) == ["-", "-"]
