"""bbox_raise + whole-frame phantom rejection (6/4 r22)."""
from __future__ import annotations

import numpy as np
import pytest
from PIL import Image

from audio.lisbon_swn_camera_bridge import (
    MOVEMENT_SOURCE_BBOX_RAISE,
    PersonObservation,
    PersonSceneTracker,
    _bbox_raise_magnitude,
    observations_from_yolo_result,
)


# --- _bbox_raise_magnitude unit tests -----------------------------------

def test_bbox_raise_zero_below_baseline():
    # aspect = 200/100 = 2.0 = baseline (boundary returns 0)
    assert _bbox_raise_magnitude(width=100, height=200) == 0.0
    # narrow standing person
    assert _bbox_raise_magnitude(width=100, height=180) == 0.0


def test_bbox_raise_saturates_above_threshold():
    # aspect = 380/100 = 3.8 > saturation 3.2 -> 1.0
    assert _bbox_raise_magnitude(width=100, height=380) == 1.0


def test_bbox_raise_scales_in_between():
    # aspect = 260/100 = 2.6
    # (2.6 - 2.0) / (3.2 - 2.0) = 0.6/1.2 = 0.5
    mag = _bbox_raise_magnitude(width=100, height=260)
    assert mag == pytest.approx(0.5, abs=1e-6)


def test_bbox_raise_handles_zero_width():
    assert _bbox_raise_magnitude(width=0.0, height=100) == 0.0


# --- tracker behaviour ------------------------------------------------

def test_tracker_bbox_raise_fires_first_frame_no_history():
    """bbox_raise is position-based — works on frame 1."""
    tracker = PersonSceneTracker(
        stillness_deadband=0.01,
        movement_source=MOVEMENT_SOURCE_BBOX_RAISE,
    )
    # bbox = 100x400 = aspect 4.0, well above saturation
    scene = tracker.update(
        [PersonObservation(track_id=1, bbox_xyxy=(50, 50, 150, 450), confidence=0.9)],
        frame_size=(640, 480), dt=0.2,
    )
    assert scene.tracks[0].movement == 1.0


def test_tracker_bbox_raise_silent_on_standing_walking():
    """Standing person bbox aspect ~1.5-1.8 = silent."""
    tracker = PersonSceneTracker(
        stillness_deadband=0.01,
        movement_source=MOVEMENT_SOURCE_BBOX_RAISE,
    )
    # bbox = 100x180 = aspect 1.8 (standing)
    scene = tracker.update(
        [PersonObservation(track_id=1, bbox_xyxy=(50, 50, 150, 230), confidence=0.9)],
        frame_size=(640, 480), dt=0.2,
    )
    assert scene.tracks[0].movement == 0.0


# --- whole-frame phantom rejection ------------------------------------

class _FakeBoxes:
    def __init__(self, xyxy, conf, cls, ids=None):
        self.xyxy = np.array(xyxy, dtype=np.float32)
        self.conf = np.array(conf, dtype=np.float32)
        self.cls = np.array(cls, dtype=np.float32)
        self.id = np.array(ids, dtype=np.float32) if ids is not None else None


class _FakeResult:
    def __init__(self, boxes):
        self.boxes = boxes
        self.keypoints = None


def test_observations_reject_whole_frame_bbox():
    """A bbox covering 80% of the frame is hallucination — drop it."""
    # 640x480 frame, bbox covers entire frame (100% area)
    result = _FakeResult(_FakeBoxes(
        xyxy=[[0, 0, 640, 480]],
        conf=[0.9],
        cls=[0],
        ids=[1],
    ))
    obs = observations_from_yolo_result(result, min_confidence=0.25, frame_size=(640, 480))
    assert obs == []


def test_observations_accept_normal_size_bbox():
    """A normal-sized person bbox (~10% of frame) must still pass."""
    result = _FakeResult(_FakeBoxes(
        xyxy=[[200, 100, 350, 380]],   # 150x280 = 0.137 of 640x480
        conf=[0.9],
        cls=[0],
        ids=[1],
    ))
    obs = observations_from_yolo_result(result, min_confidence=0.25, frame_size=(640, 480))
    assert len(obs) == 1
    assert obs[0].track_id == 1


def test_observations_reject_70_percent_bbox_at_boundary():
    """Boundary check: 70% area is rejected (gate is >=)."""
    # 640x480 = 307200 px². 70% = 215040. Make a bbox 530x406 ≈ 215180 px² (just above 70%)
    result = _FakeResult(_FakeBoxes(
        xyxy=[[20, 20, 550, 426]],
        conf=[0.9],
        cls=[0],
        ids=[1],
    ))
    obs = observations_from_yolo_result(result, min_confidence=0.25, frame_size=(640, 480))
    assert obs == []
