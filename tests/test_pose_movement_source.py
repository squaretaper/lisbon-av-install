"""Tests for the pose-based movement source (6/4 r17).

Covers:
- PersonObservation carrying keypoints
- _max_keypoint_delta with confidence gating + missing keypoints
- PersonSceneTracker.movement_source=pose path picking up wrist motion
- Fallback to bbox when keypoints unavailable or all unconfident
- set_tuning honouring movement_source flips and rejecting invalid values
- tune.py round-trip with movement_source string
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from audio.lisbon_swn_camera_bridge import (
    MOVEMENT_SOURCE_BBOX,
    MOVEMENT_SOURCE_POSE,
    PersonObservation,
    PersonSceneTracker,
    _max_keypoint_delta,
)


def test_max_keypoint_delta_picks_largest_confident_keypoint_motion():
    prev = {
        0: (0.5, 0.5, 0.9),    # nose
        9: (0.4, 0.6, 0.9),    # L wrist
        10: (0.6, 0.6, 0.2),   # R wrist — low confidence, must be ignored
    }
    curr = {
        0: (0.5, 0.5, 0.9),    # nose still
        9: (0.4, 0.2, 0.9),    # L wrist moved 0.4 in y
        10: (0.9, 0.9, 0.2),   # huge jump but low conf -> ignored
    }
    assert _max_keypoint_delta(prev, curr) == pytest.approx(0.4, abs=1e-9)


def test_max_keypoint_delta_zero_when_no_shared_confident_keypoints():
    prev = {0: (0.5, 0.5, 0.9)}
    curr = {9: (0.4, 0.4, 0.9)}  # different keypoint id
    assert _max_keypoint_delta(prev, curr) == 0.0


def test_pose_tracker_fires_on_wrist_wave_below_bbox_threshold():
    """A hand wave barely moves bbox center but moves the wrist a lot.
    Pose source should expose that motion; bbox source would gate it.
    """
    tracker = PersonSceneTracker(
        max_missing=8, match_threshold=0.4,
        stillness_deadband=0.01, movement_source=MOVEMENT_SOURCE_POSE,
    )
    bbox = (100.0, 100.0, 200.0, 400.0)  # 100x300 box, center (150, 250)
    # Frame 1: prime memory
    tracker.update(
        [PersonObservation(
            track_id=1, bbox_xyxy=bbox, confidence=0.9,
            keypoints={9: (0.30, 0.50, 0.9), 10: (0.40, 0.50, 0.9)},
        )],
        frame_size=(640, 480), dt=0.2,
    )
    # Frame 2: bbox unchanged, R wrist swept 0.3 to the right
    scene = tracker.update(
        [PersonObservation(
            track_id=1, bbox_xyxy=bbox, confidence=0.9,
            keypoints={9: (0.30, 0.50, 0.9), 10: (0.70, 0.50, 0.9)},
        )],
        frame_size=(640, 480), dt=0.2,
    )
    assert scene.tracks
    # 0.3 / max(0.03, 0.2*0.65=0.13) = 2.3 -> clamped to 1.0
    assert scene.tracks[0].movement == pytest.approx(1.0, abs=1e-9)


def test_pose_tracker_gates_on_slow_walk_translating_bbox_but_not_keypoints():
    """Walking translates the whole body, but in the pose signal the
    *relative* keypoint position barely changes between frames if dt is
    small. With pose mode, slow walking should produce a small delta —
    below the deadband — while bbox mode would fire.
    """
    tracker = PersonSceneTracker(
        max_missing=8, match_threshold=0.4,
        stillness_deadband=0.05, movement_source=MOVEMENT_SOURCE_POSE,
    )
    # Frame 1
    tracker.update(
        [PersonObservation(
            track_id=1, bbox_xyxy=(100, 100, 200, 400), confidence=0.9,
            keypoints={9: (0.30, 0.50, 0.9), 10: (0.40, 0.50, 0.9)},
        )],
        frame_size=(640, 480), dt=0.2,
    )
    # Frame 2: bbox shifted right by 30px but wrists shifted same amount
    # (whole body translated). Per-keypoint delta = 30/640 ≈ 0.047 — under deadband.
    scene = tracker.update(
        [PersonObservation(
            track_id=1, bbox_xyxy=(130, 100, 230, 400), confidence=0.9,
            keypoints={9: (0.347, 0.50, 0.9), 10: (0.447, 0.50, 0.9)},
        )],
        frame_size=(640, 480), dt=0.2,
    )
    assert scene.tracks[0].movement == 0.0  # gated by deadband


def test_pose_mode_falls_back_to_bbox_when_keypoints_missing():
    """If a frame's obs has no keypoints (e.g. fully occluded), the pose
    path silently falls back to bbox delta — we never mute motion just
    because the pose model lost track of limbs.
    """
    tracker = PersonSceneTracker(
        stillness_deadband=0.01, movement_source=MOVEMENT_SOURCE_POSE,
    )
    # Frame 1: with keypoints
    tracker.update(
        [PersonObservation(
            track_id=1, bbox_xyxy=(100, 100, 200, 400), confidence=0.9,
            keypoints={9: (0.30, 0.50, 0.9)},
        )],
        frame_size=(640, 480), dt=0.2,
    )
    # Frame 2: NO keypoints, but bbox moved 100px (huge translation)
    scene = tracker.update(
        [PersonObservation(
            track_id=1, bbox_xyxy=(200, 100, 300, 400), confidence=0.9,
            keypoints=None,
        )],
        frame_size=(640, 480), dt=0.2,
    )
    assert scene.tracks[0].movement > 0.0


def test_set_tuning_flips_movement_source_live():
    tracker = PersonSceneTracker(movement_source=MOVEMENT_SOURCE_BBOX)
    assert tracker.movement_source == MOVEMENT_SOURCE_BBOX
    tracker.set_tuning(movement_source="pose")
    assert tracker.movement_source == MOVEMENT_SOURCE_POSE
    tracker.set_tuning(movement_source="bbox")
    assert tracker.movement_source == MOVEMENT_SOURCE_BBOX


def test_set_tuning_ignores_invalid_movement_source_without_crashing():
    tracker = PersonSceneTracker(movement_source=MOVEMENT_SOURCE_BBOX)
    tracker.set_tuning(movement_source="garbage")
    assert tracker.movement_source == MOVEMENT_SOURCE_BBOX  # unchanged


def test_tracker_rejects_invalid_movement_source_at_construction():
    with pytest.raises(ValueError):
        PersonSceneTracker(movement_source="dance")


def test_tune_script_round_trips_movement_source_as_string(tmp_path, monkeypatch):
    """tune.py must not coerce movement_source to float (would crash) and
    must reject unknown values like 'lidar'."""
    import importlib.util
    repo = Path(__file__).resolve().parent.parent
    spec = importlib.util.spec_from_file_location("tune_pose", repo / "scripts" / "tune.py")
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    monkeypatch.setattr(mod, "TUNE_PATH", tmp_path / "tune.json")
    monkeypatch.setattr(mod, "LEGACY_PROFILE_PATH", tmp_path / "heuristic_profile.json")

    mod.apply(["movement_source=pose"])
    written = json.loads(mod.TUNE_PATH.read_text())
    assert written == {"movement_source": "pose"}

    mod.apply(["movement_source=bbox"])
    written = json.loads(mod.TUNE_PATH.read_text())
    assert written == {"movement_source": "bbox"}

    with pytest.raises(SystemExit):
        mod.apply(["movement_source=lidar"])
