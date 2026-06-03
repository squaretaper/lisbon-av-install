import math
import sys
from pathlib import Path

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from audio.lisbon_swn_camera_bridge import (
    CameraFeatures,
    CameraFeatureTracker,
    HumanAwareSwnMapper,
    LisbonSwnMapper,
    MOVEMENT_GATE_CV_INDEX,
    PersonObservation,
    PersonScene,
    PersonSceneTracker,
    analyze_audio_block,
    annotate_person_scene,
    build_arg_parser,
    fill_output_block,
    hold_person_cv_for_still_frame,
    measure_input_audio,
    observations_from_yolo_result,
    physical_cv_to_coreaudio_channel,
    quiet_person_scene,
)


def test_audio_status_writer_has_low_latency_default_independent_of_camera_hz():
    args = build_arg_parser().parse_args([])

    assert args.status_hz >= 40.0
    assert args.blocksize <= 128
    assert args.camera_hz <= args.status_hz
    assert args.stillness_deadband >= 0.03
    assert args.stillness_frame_motion >= 0.03


def test_physical_es9_cv_outputs_map_to_coreaudio_outputs_9_to_16():
    assert [physical_cv_to_coreaudio_channel(i) for i in range(1, 9)] == list(range(8, 16))


def test_camera_feature_tracker_reports_motion_and_centroid_shift():
    tracker = CameraFeatureTracker(sample_size=(8, 4))
    dark = Image.new("RGB", (16, 8), (0, 0, 0))
    bright_right = Image.new("RGB", (16, 8), (0, 0, 0))
    px = bright_right.load()
    for y in range(8):
        for x in range(8, 16):
            px[x, y] = (255, 255, 255)

    first = tracker.update(dark)
    second = tracker.update(bright_right)

    assert first.motion == 0.0
    assert second.motion > 0.45
    assert second.brightness > 0.45
    assert second.centroid_x > 0.65


def test_mapper_keeps_pitch_cv_safe_and_moves_global_params_with_camera_activity():
    mapper = LisbonSwnMapper(max_cv=0.25, smoothing_hz=20.0)
    calm = mapper.step(brightness=0.05, motion=0.0, centroid_x=0.5, centroid_y=0.5, dt=0.1)
    active = mapper.step(brightness=0.8, motion=0.9, centroid_x=0.9, centroid_y=0.2, dt=0.1)

    assert len(calm) == 8
    assert len(active) == 8
    assert all(0.0 <= value <= 0.25 for value in active)

    # CV1-3 are 1V/oct voices: mostly stable chord degrees with only tiny camera drift.
    assert math.isclose(calm[0], 0.0, abs_tol=0.02)
    assert 0.045 <= calm[1] <= 0.075  # fifth-ish offset, ~7 semitones
    assert 0.085 <= calm[2] <= 0.115  # octave-ish offset
    assert abs(active[0] - calm[0]) <= 0.02
    assert abs(active[1] - calm[1]) <= 0.02
    assert abs(active[2] - calm[2]) <= 0.02

    # CV4-8 should respond upward or sideways to active camera input.
    assert active[3] > calm[3]  # wavetable browse follows horizontal mass/motion
    assert active[4] > calm[4]  # dispersion follows motion
    assert active[6] > calm[6]  # movement gate follows camera/room motion
    assert active[7] > calm[7]  # depth follows activity


def test_person_scene_tracker_preserves_id_and_reports_distance_motion():
    tracker = PersonSceneTracker(max_missing=2)
    # bboxes sized so neither saturates the area-based distance mapping
    # (window is 0.02..0.12 of frame area, so target areas ~0.04..0.10).
    # Frame 200x200 = 40000 px. Small box 32x40=1280 = 0.032 area (far).
    # Larger box 48x60=2880 = 0.072 area (closer).
    first = tracker.update(
        [PersonObservation(track_id=None, bbox_xyxy=(40, 30, 72, 70), confidence=0.9)],
        frame_size=(200, 200),
        dt=0.2,
    )
    second = tracker.update(
        [PersonObservation(track_id=None, bbox_xyxy=(54, 20, 102, 80), confidence=0.92)],
        frame_size=(200, 200),
        dt=0.2,
    )

    assert first.people_count == 1
    assert second.people_count == 1
    assert second.tracks[0].id == first.tracks[0].id
    assert second.tracks[0].distance > first.tracks[0].distance
    assert second.tracks[0].movement > 0.05
    assert 0.0 <= second.activity <= 1.0


def test_person_scene_tracker_deadbands_detector_jitter_for_stationary_people():
    tracker = PersonSceneTracker(max_missing=2)
    first = tracker.update(
        [PersonObservation(track_id=7, bbox_xyxy=(40, 30, 110, 160), confidence=0.9)],
        frame_size=(200, 200),
        dt=0.25,
    )
    second = tracker.update(
        [PersonObservation(track_id=7, bbox_xyxy=(40.4, 30.2, 110.4, 160.2), confidence=0.9)],
        frame_size=(200, 200),
        dt=0.25,
    )

    assert second.tracks[0].movement == 0.0
    assert math.isclose(second.tracks[0].center_x, first.tracks[0].center_x, abs_tol=1e-9)
    assert math.isclose(second.tracks[0].distance, first.tracks[0].distance, abs_tol=1e-9)
    assert second.activity < 0.05


def test_low_frame_motion_holds_person_cv_and_quiets_detection_jitter():
    tracker = PersonSceneTracker(max_missing=2, stillness_deadband=0.0)
    tracker.update(
        [PersonObservation(track_id=3, bbox_xyxy=(40, 30, 110, 160), confidence=0.9)],
        frame_size=(200, 200),
        dt=0.25,
    )
    jittery_scene = tracker.update(
        [PersonObservation(track_id=3, bbox_xyxy=(48, 32, 118, 162), confidence=0.9)],
        frame_size=(200, 200),
        dt=0.25,
    )
    features = CameraFeatures(brightness=0.25, motion=0.010, centroid_x=0.5, centroid_y=0.5)

    assert jittery_scene.movement > 0.0
    assert hold_person_cv_for_still_frame(features, jittery_scene, frame_motion_threshold=0.015)
    quiet = quiet_person_scene(jittery_scene)
    assert quiet.movement == 0.0
    assert quiet.activity == 0.0
    assert all(track.movement == 0.0 for track in quiet.tracks)


def test_person_scene_tracker_summarizes_count_spread_and_nearest_distance():
    tracker = PersonSceneTracker(max_missing=2)
    scene = tracker.update(
        [
            PersonObservation(track_id=41, bbox_xyxy=(10, 50, 50, 150), confidence=0.9),
            PersonObservation(track_id=42, bbox_xyxy=(130, 20, 195, 198), confidence=0.8),
        ],
        frame_size=(200, 200),
        dt=0.1,
    )

    assert scene.people_count == 2
    assert [track.id for track in scene.tracks] == [41, 42]
    assert scene.centroid_x > 0.5  # larger/nearer right person pulls mass right
    assert scene.spread_x > 0.45
    assert scene.nearest_distance > 0.75


def test_human_aware_mapper_is_graduated_not_binary_and_uses_people_count_distance():
    tracker = PersonSceneTracker(max_missing=2)
    mapper = HumanAwareSwnMapper(max_cv=0.22, smoothing_hz=20.0)
    empty = tracker.update([], frame_size=(200, 200), dt=0.1)
    far_one = tracker.update(
        [PersonObservation(track_id=1, bbox_xyxy=(70, 65, 115, 155), confidence=0.9)],
        frame_size=(200, 200),
        dt=0.1,
    )
    close_two = tracker.update(
        [
            PersonObservation(track_id=1, bbox_xyxy=(40, 20, 120, 198), confidence=0.9),
            PersonObservation(track_id=2, bbox_xyxy=(125, 35, 190, 185), confidence=0.85),
        ],
        frame_size=(200, 200),
        dt=0.1,
    )

    cv_empty = mapper.step_scene(empty, dt=0.1)
    cv_far = mapper.step_scene(far_one, dt=0.1)
    cv_close = mapper.step_scene(close_two, dt=0.1)

    assert len(cv_close) == 8
    assert all(0.0 <= value <= 0.22 for value in cv_close)
    assert cv_empty != cv_far != cv_close

    # Person distance/count should create gradual increases in the timbral CVs.
    assert cv_close[4] > cv_far[4] > cv_empty[4]  # dispersion
    assert cv_close[7] > cv_far[7] > cv_empty[7]  # depth/proximity

    # CV7 is now patched as a movement gate, so mere presence/spread should not open it.
    assert cv_empty[MOVEMENT_GATE_CV_INDEX] <= 0.002
    assert cv_far[MOVEMENT_GATE_CV_INDEX] <= 0.002

    # Pattern is continuous now, not floor()/integer stepping.
    assert not math.isclose(cv_far[5], cv_close[5], abs_tol=0.002)

    # Pitch voices stay musical/safe but identify people through small, stable offsets.
    assert abs(cv_close[0] - cv_empty[0]) <= 0.05
    assert abs(cv_close[1] - cv_empty[1]) <= 0.05
    assert abs(cv_close[2] - cv_empty[2]) <= 0.05


def _person_scene_for_test(*, movement: float, activity: float, people_count: int = 2, spread_x: float = 0.55) -> PersonScene:
    return PersonScene(
        people_count=people_count,
        tracks=[],
        centroid_x=0.5,
        centroid_y=0.65,
        spread_x=spread_x,
        nearest_distance=0.7,
        mean_distance=0.65,
        movement=movement,
        activity=activity,
        count_norm=min(1.0, people_count / 4.0),
    )


def test_cv7_is_a_smoothed_room_movement_gate_not_presence_or_spread():
    mapper = HumanAwareSwnMapper(max_cv=0.18, smoothing_hz=20.0)
    still_crowd = _person_scene_for_test(movement=0.0, activity=0.0, people_count=3, spread_x=0.85)
    moving_room = _person_scene_for_test(movement=0.55, activity=0.55, people_count=3, spread_x=0.85)

    cv_still = mapper.step_scene(still_crowd, dt=1.0)
    cv_moving = mapper.step_scene(moving_room, dt=0.25)

    assert cv_still[MOVEMENT_GATE_CV_INDEX] <= 0.002
    assert cv_moving[MOVEMENT_GATE_CV_INDEX] > 0.08
    assert cv_moving[MOVEMENT_GATE_CV_INDEX] <= 0.18


def test_still_frame_hold_decays_cv7_and_cv6_while_freezing_pitch_cvs():
    """Stillness should still let CV6 (mix VCA) track presence and CV7
    (glitch) decay, but freeze CV1-5 + CV8 to avoid detector jitter on
    pitch and timbral controls.

    Live tuning 6/3: original behavior froze CV6 too, making the mix
    volume stuck whenever the room was quiet. Now CV6 stays live so a
    person walking up to a quiet room still hears the volume swell.
    """
    from audio.lisbon_swn_camera_bridge import MAIN_MIX_VCA_CV_INDEX
    mapper = HumanAwareSwnMapper(max_cv=0.18, smoothing_hz=20.0)
    moving_room = _person_scene_for_test(movement=0.75, activity=0.75)
    quiet_room = _person_scene_for_test(movement=0.0, activity=0.0)

    hot = mapper.step_scene(moving_room, dt=1.0)
    held = mapper.step_movement_gate_only(quiet_room, hot, dt=0.25)

    for index, (before, after) in enumerate(zip(hot, held)):
        if index == MOVEMENT_GATE_CV_INDEX:
            # glitch decays
            assert after < before
            assert after <= 0.02
        elif index == MAIN_MIX_VCA_CV_INDEX:
            # mix VCA tracks presence — quiet room has no presence so it should drop too
            assert after <= before
        else:
            # pitch + timbral CVs frozen
            assert math.isclose(after, before, abs_tol=1e-9)


def test_yolo_result_adapter_extracts_person_observations_with_track_ids():
    class FakeBoxes:
        xyxy = np.array([[10, 20, 50, 100], [1, 2, 3, 4], [90, 30, 150, 190]], dtype=np.float32)
        conf = np.array([0.91, 0.99, 0.42], dtype=np.float32)
        cls = np.array([0, 2, 0], dtype=np.float32)
        id = np.array([7, 8, 9], dtype=np.float32)

    class FakeResult:
        boxes = FakeBoxes()

    observations = observations_from_yolo_result(FakeResult(), min_confidence=0.5)

    assert observations == [PersonObservation(track_id=7, bbox_xyxy=(10.0, 20.0, 50.0, 100.0), confidence=0.91)]


def test_annotated_preview_draws_people_and_scene_text():
    image = Image.new("RGB", (120, 90), (8, 8, 8))
    scene = PersonSceneTracker().update(
        [PersonObservation(track_id=3, bbox_xyxy=(20, 15, 80, 85), confidence=0.88)],
        frame_size=(120, 90),
        dt=0.1,
    )

    annotated = annotate_person_scene(image, scene)

    assert annotated.size == image.size
    assert np.mean(np.abs(np.asarray(annotated, dtype=np.int16) - np.asarray(image, dtype=np.int16))) > 0.5
    assert tuple(annotated.getpixel((20, 15))) != (8, 8, 8)


def test_measure_input_audio_reports_rms_and_peak_for_es9_inputs_1_2():
    indata = np.zeros((4, 16), dtype=np.float32)
    indata[:, 0] = [0.0, 0.5, -0.5, 0.0]
    indata[:, 1] = [0.25, -0.25, 0.25, -0.25]

    telemetry = measure_input_audio(indata, blocks=12)

    assert telemetry["blocks"] == 12
    assert telemetry["source_input_channels"] == [1, 2]
    assert math.isclose(telemetry["input_1_rms"], math.sqrt(0.5 / 4), rel_tol=1e-6)
    assert math.isclose(telemetry["input_2_rms"], 0.25, rel_tol=1e-6)
    assert telemetry["input_1_peak"] == 0.5
    assert telemetry["input_2_peak"] == 0.25


def test_measure_input_audio_can_listen_to_non_default_es9_input_pair():
    indata = np.zeros((4, 16), dtype=np.float32)
    indata[:, 4] = [0.0, 0.4, -0.4, 0.0]
    indata[:, 5] = [0.1, -0.1, 0.1, -0.1]

    telemetry = measure_input_audio(indata, blocks=7, input_channels=(5, 6))

    assert telemetry["source_input_channels"] == [5, 6]
    assert math.isclose(telemetry["input_1_rms"], math.sqrt(0.32 / 4), rel_tol=1e-6)
    assert math.isclose(telemetry["input_2_rms"], 0.1, rel_tol=1e-6)
    assert math.isclose(telemetry["input_1_peak"], 0.4, rel_tol=1e-6)
    assert math.isclose(telemetry["input_2_peak"], 0.1, rel_tol=1e-6)


def test_analyze_audio_block_reports_frequency_and_glitch_score():
    sample_rate = 48_000
    n = 1024
    t = np.arange(n, dtype=np.float32) / sample_rate
    low = 0.25 * np.sin(2 * math.pi * 220 * t)
    high = 0.25 * np.sin(2 * math.pi * 4200 * t)
    impulse = np.zeros(n, dtype=np.float32)
    impulse[128] = 0.95
    impulse[129] = -0.95

    low_features = analyze_audio_block(np.column_stack([low, low]), sample_rate=sample_rate, previous_peak=0.25)
    high_features = analyze_audio_block(np.column_stack([high, high]), sample_rate=sample_rate, previous_peak=0.25)
    glitch_features = analyze_audio_block(np.column_stack([impulse, impulse]), sample_rate=sample_rate, previous_peak=0.05)

    assert high_features["zero_crossing_hz"] > low_features["zero_crossing_hz"] * 8
    assert high_features["dominant_frequency_hz"] > low_features["dominant_frequency_hz"] * 8
    assert high_features["spectral_centroid_hz"] > low_features["spectral_centroid_hz"] * 8
    assert low_features["low_band_ratio"] > 0.7
    assert high_features["high_band_ratio"] > 0.7
    assert high_features["high_freq_ratio"] > low_features["high_freq_ratio"]
    assert glitch_features["glitch_score"] > 0.5
    assert glitch_features["transient_score"] == glitch_features["transient"]


def test_fill_output_block_routes_stereo_audio_and_writes_dc_cv_to_outputs_9_to_16():
    indata = np.zeros((4, 16), dtype=np.float32)
    indata[:, 0] = [0.1, -0.1, 0.2, -0.2]
    indata[:, 1] = [0.3, -0.3, 0.4, -0.4]
    outdata = np.full((4, 16), 99.0, dtype=np.float32)
    cv = [0.01, 0.02, 0.03, 0.04, 0.05, 0.06, 0.07, 0.08]

    fill_output_block(outdata, indata, cv, main_gain=0.5)

    assert np.allclose(outdata[:, 0], indata[:, 0] * 0.5)
    assert np.allclose(outdata[:, 1], indata[:, 1] * 0.5)
    assert np.allclose(outdata[:, 2:8], 0.0)
    for i, value in enumerate(cv, start=8):
        assert np.allclose(outdata[:, i], value)


def test_fill_output_block_can_monitor_a_non_default_es9_input_pair():
    indata = np.zeros((4, 16), dtype=np.float32)
    indata[:, 6] = [0.2, -0.2, 0.3, -0.3]
    indata[:, 7] = [0.4, -0.4, 0.5, -0.5]
    outdata = np.full((4, 16), 99.0, dtype=np.float32)
    cv = [0.0] * 8

    fill_output_block(outdata, indata, cv, main_gain=0.25, input_channels=(7, 8))

    assert np.allclose(outdata[:, 0], indata[:, 6] * 0.25)
    assert np.allclose(outdata[:, 1], indata[:, 7] * 0.25)
    assert np.allclose(outdata[:, 2:16], 0.0)
