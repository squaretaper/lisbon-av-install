"""Pose overlay rendering tests (6/4 r18).

PIL doesn't make it easy to assert *exactly* which pixel changed, so
these tests check the overlay path doesn't crash on edge cases and
that the rendered image actually changes when keypoints are present.
"""
from __future__ import annotations

import numpy as np
from PIL import Image

from audio.lisbon_swn_camera_bridge import (
    PersonScene,
    PersonTrack,
    annotate_person_scene,
)


def _blank_scene_with_track(keypoints=None):
    track = PersonTrack(
        id=1,
        bbox_xyxy=(40.0, 20.0, 200.0, 460.0),
        confidence=0.9,
        center_x=0.375,   # (40+200)/2 / 640
        center_y=0.5,
        width=160.0 / 640,
        height=440.0 / 480,
        area=0.23,
        distance=0.6,
        movement=0.4,
        age=12,
        keypoints=keypoints,
    )
    return PersonScene(
        people_count=1,
        tracks=[track],
        centroid_x=0.375,
        centroid_y=0.5,
        spread_x=0.0,
        nearest_distance=0.6,
        mean_distance=0.6,
        movement=0.4,
        activity=0.4,
        count_norm=0.25,
    )


def test_overlay_renders_without_keypoints():
    """Bbox-only mode: skeleton path must be silent, image still valid."""
    base = Image.new("RGB", (640, 480), (8, 8, 8))
    out = annotate_person_scene(base, _blank_scene_with_track(keypoints=None))
    assert out.size == (640, 480)
    # something was drawn (bbox + centroid + label bar)
    assert np.asarray(out).sum() > np.asarray(base).sum()


def test_overlay_renders_skeleton_when_keypoints_present():
    """Pose mode: skeleton should add pixels beyond the bbox-only render."""
    base = Image.new("RGB", (640, 480), (8, 8, 8))
    bbox_only = annotate_person_scene(base, _blank_scene_with_track(keypoints=None))
    keypoints = {
        0: (0.375, 0.10, 0.95),    # nose
        5: (0.30, 0.20, 0.92),     # L shoulder
        6: (0.45, 0.20, 0.92),     # R shoulder
        9: (0.20, 0.42, 0.88),     # L wrist
        10: (0.55, 0.42, 0.88),    # R wrist
        11: (0.32, 0.55, 0.90),    # L hip
        12: (0.43, 0.55, 0.90),    # R hip
        15: (0.30, 0.92, 0.85),    # L ankle
        16: (0.45, 0.92, 0.85),    # R ankle
    }
    with_skeleton = annotate_person_scene(base, _blank_scene_with_track(keypoints=keypoints))
    # Skeleton overlay must add visible pixels
    assert np.asarray(with_skeleton).sum() > np.asarray(bbox_only).sum()


def test_overlay_skips_low_confidence_keypoints():
    """A keypoint with conf < 0.4 must not contribute pixels."""
    base = Image.new("RGB", (640, 480), (8, 8, 8))
    high_conf = annotate_person_scene(
        base,
        _blank_scene_with_track(keypoints={9: (0.20, 0.42, 0.9), 10: (0.55, 0.42, 0.9)}),
    )
    low_conf = annotate_person_scene(
        base,
        _blank_scene_with_track(keypoints={9: (0.20, 0.42, 0.1), 10: (0.55, 0.42, 0.1)}),
    )
    # High-conf overlay strictly brighter than low-conf overlay
    assert np.asarray(high_conf).sum() > np.asarray(low_conf).sum()


def test_overlay_clips_keypoints_outside_frame():
    """Out-of-frame keypoint coords must not raise or write outside the image."""
    base = Image.new("RGB", (640, 480), (8, 8, 8))
    # x_norm = 1.5 → off-screen right; should be silently dropped
    out = annotate_person_scene(
        base,
        _blank_scene_with_track(keypoints={9: (1.5, 0.5, 0.9), 10: (-0.2, 0.5, 0.9)}),
    )
    assert out.size == (640, 480)
