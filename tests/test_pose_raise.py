"""pose_raise movement source (6/4 r20).

Postural trigger: fires only when wrist is above the matching elbow.
Magnitude scales with how far the wrist climbs past the elbow,
saturating at ~upper-arm-length of frame height. Position signal —
no dt scaling — so drop happens instantly on the next frame.

Operator intent: walking / dancing / fast motion = silent, deliberate
arm raise = full glitch. Arms-down decays via the CV7 latch's
existing exp release.
"""
from __future__ import annotations

import pytest

from audio.lisbon_swn_camera_bridge import (
    MOVEMENT_SOURCE_POSE_RAISE,
    PersonObservation,
    PersonSceneTracker,
    _raise_magnitude,
)


# Image coords: y=0 at the top. wrist above elbow means wrist_y < elbow_y.
# Saturation = 0.15 of normalised height.


def test_raise_magnitude_zero_when_no_keypoints():
    assert _raise_magnitude(None) == 0.0
    assert _raise_magnitude({}) == 0.0


def test_raise_magnitude_zero_when_arms_hanging_down():
    kp = {
        7: (0.3, 0.45, 0.9),   # L elbow
        9: (0.3, 0.60, 0.9),   # L wrist BELOW elbow
        8: (0.7, 0.45, 0.9),   # R elbow
        10: (0.7, 0.60, 0.9),  # R wrist BELOW elbow
    }
    assert _raise_magnitude(kp) == 0.0


def test_raise_magnitude_saturates_at_one_when_wrist_well_above_elbow():
    # Wrist 0.30 above elbow (way past saturation 0.15)
    kp = {
        7: (0.3, 0.50, 0.9),
        9: (0.3, 0.20, 0.9),
    }
    assert _raise_magnitude(kp) == 1.0


def test_raise_magnitude_partial_when_wrist_just_above_elbow():
    # Elevation = 0.05, half of saturation 0.15 = ~0.33
    kp = {
        7: (0.3, 0.45, 0.9),
        9: (0.3, 0.40, 0.9),  # 0.05 above
    }
    mag = _raise_magnitude(kp)
    assert 0.30 < mag < 0.36


def test_raise_magnitude_picks_max_of_two_arms():
    kp = {
        7: (0.3, 0.45, 0.9),    # L elbow
        9: (0.3, 0.43, 0.9),    # L wrist barely above (~0.13)
        8: (0.7, 0.50, 0.9),    # R elbow
        10: (0.7, 0.20, 0.9),   # R wrist way above
    }
    # Right arm wins
    assert _raise_magnitude(kp) == 1.0


def test_raise_magnitude_ignores_low_confidence_keypoints():
    kp = {
        7: (0.3, 0.45, 0.9),
        9: (0.3, 0.20, 0.15),   # wrist below conf threshold
    }
    assert _raise_magnitude(kp) == 0.0


def test_tracker_pose_raise_fires_first_frame_no_history_needed():
    """Unlike velocity-based pose mode which needs two frames to
    compute a delta, pose_raise is purely positional. A person walking
    into the room with arms already raised should fire on frame 1.
    """
    tracker = PersonSceneTracker(
        stillness_deadband=0.01,
        movement_source=MOVEMENT_SOURCE_POSE_RAISE,
    )
    kp = {7: (0.3, 0.50, 0.9), 9: (0.3, 0.20, 0.9)}  # L arm fully raised
    # First frame
    scene = tracker.update(
        [PersonObservation(track_id=1, bbox_xyxy=(100, 100, 200, 400),
                           confidence=0.9, keypoints=kp)],
        frame_size=(640, 480), dt=0.2,
    )
    # r21 fix: pose_raise now fires from frame 1 (was 0.0 — the bug)
    assert scene.tracks[0].movement == 1.0
    # Second frame, arm still up
    scene = tracker.update(
        [PersonObservation(track_id=1, bbox_xyxy=(100, 100, 200, 400),
                           confidence=0.9, keypoints=kp)],
        frame_size=(640, 480), dt=0.2,
    )
    assert scene.tracks[0].movement == 1.0


def test_tracker_pose_raise_drops_instantly_on_arm_down(tmp_path, monkeypatch):
    """Arm-down on the very next frame should report movement=0,
    not decay slowly. The CV7 latch handles smooth release downstream."""
    tracker = PersonSceneTracker(
        stillness_deadband=0.01,
        movement_source=MOVEMENT_SOURCE_POSE_RAISE,
    )
    raised = {7: (0.3, 0.50, 0.9), 9: (0.3, 0.20, 0.9)}
    lowered = {7: (0.3, 0.50, 0.9), 9: (0.3, 0.70, 0.9)}  # wrist BELOW elbow

    tracker.update(
        [PersonObservation(track_id=1, bbox_xyxy=(100, 100, 200, 400),
                           confidence=0.9, keypoints=raised)],
        frame_size=(640, 480), dt=0.2,
    )
    # Establish raised baseline
    scene = tracker.update(
        [PersonObservation(track_id=1, bbox_xyxy=(100, 100, 200, 400),
                           confidence=0.9, keypoints=raised)],
        frame_size=(640, 480), dt=0.2,
    )
    assert scene.tracks[0].movement == 1.0
    # Drop arms
    scene = tracker.update(
        [PersonObservation(track_id=1, bbox_xyxy=(100, 100, 200, 400),
                           confidence=0.9, keypoints=lowered)],
        frame_size=(640, 480), dt=0.2,
    )
    assert scene.tracks[0].movement == 0.0


def test_tracker_pose_raise_silent_on_walking_with_arms_at_side():
    """Walking person with arms at side must not fire CV7."""
    tracker = PersonSceneTracker(
        stillness_deadband=0.01,
        movement_source=MOVEMENT_SOURCE_POSE_RAISE,
    )
    # Walk across frame, arms at side every frame
    for x_shift in (0, 50, 100, 150):
        kp = {
            7: (0.30 + x_shift / 1000, 0.50, 0.9),
            9: (0.30 + x_shift / 1000, 0.70, 0.9),   # wrist below elbow
        }
        scene = tracker.update(
            [PersonObservation(track_id=1, bbox_xyxy=(100 + x_shift, 100, 200 + x_shift, 400),
                               confidence=0.9, keypoints=kp)],
            frame_size=(640, 480), dt=0.2,
        )
    # Final frame should report no gesture even though the bbox has translated 150px
    assert scene.tracks[0].movement == 0.0


def test_raise_magnitude_ignores_head_only_detections():
    """Person cropped to head/shoulders at top of frame: pose model
    sometimes hallucinates elbow/wrist keypoints clustered in the top
    10% of frame. These produce phantom fires. Should be skipped."""
    kp = {
        7: (0.30, 0.05, 0.7),    # L elbow in top 5% of frame
        9: (0.30, 0.02, 0.7),    # L wrist also in top 5% — head-only crop
    }
    assert _raise_magnitude(kp) == 0.0


def test_raise_magnitude_still_fires_if_only_one_keypoint_is_high():
    """If wrist is high in frame but elbow is well below (genuine
    arm raise from below), the signal must still fire."""
    kp = {
        7: (0.30, 0.40, 0.9),    # elbow at mid-frame
        9: (0.30, 0.05, 0.9),    # wrist high — real raise
    }
    assert _raise_magnitude(kp) > 0.5  # big elevation


def test_tracker_pose_raise_fires_on_first_frame_with_arms_raised():
    """ByteTrack id churn produces frequent first-frame allocations
    during motion. pose_raise is a position signal — it must fire on
    frame 1 with arms up, not wait for a previous frame."""
    tracker = PersonSceneTracker(
        stillness_deadband=0.01,
        movement_source=MOVEMENT_SOURCE_POSE_RAISE,
    )
    kp = {7: (0.30, 0.50, 0.9), 9: (0.30, 0.20, 0.9)}  # arm fully raised
    scene = tracker.update(
        [PersonObservation(track_id=42, bbox_xyxy=(100, 100, 200, 400),
                           confidence=0.9, keypoints=kp)],
        frame_size=(640, 480), dt=0.2,
    )
    # First frame must report the raise — was 0.0 before the fix
    assert scene.tracks[0].movement == 1.0


def test_tune_script_round_trips_pose_raise_value(tmp_path, monkeypatch):
    import importlib.util, json
    from pathlib import Path
    repo = Path(__file__).resolve().parent.parent
    spec = importlib.util.spec_from_file_location("tune_pr", repo / "scripts" / "tune.py")
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    monkeypatch.setattr(mod, "TUNE_PATH", tmp_path / "tune.json")
    monkeypatch.setattr(mod, "LEGACY_PROFILE_PATH", tmp_path / "heuristic_profile.json")

    mod.apply(["movement_source=pose_raise"])
    written = json.loads(mod.TUNE_PATH.read_text())
    assert written == {"movement_source": "pose_raise"}
