"""Tests for the 6/5 r2 wrist-elevation postural feature and EMA smoothing.

These tests pin the contract that fixes the standing-still false-fire bug:
the postural signal must be 0 when arms hang at sides, even when keypoints
are confident; it must fire only when wrists project above shoulders in
image coordinates; and the EMA smoothing must reject 1-frame keypoint spikes.
"""
from __future__ import annotations

import pytest

from audio.lisbon_swn_camera_bridge import (
    MOVEMENT_SOURCE_ELEVATION_OR_VELOCITY,
    PersonObservation,
    PersonSceneTracker,
    _wrist_elevation_magnitude,
)


def _kp(items: dict[int, tuple[float, float, float]]) -> dict[int, tuple[float, float, float]]:
    """Build a keypoints dict with sensible defaults for omitted indices."""
    return {int(k): (float(v[0]), float(v[1]), float(v[2])) for k, v in items.items()}


# Image-y convention: y=0 is TOP of frame. Larger y = further down.
# Shoulder line at y=0.30, hip line at y=0.55 → torso_v = 0.25.
SHOULDERS_HIPS = {
    5: (0.40, 0.30, 0.95),  # L_shoulder
    6: (0.60, 0.30, 0.95),  # R_shoulder
    11: (0.42, 0.55, 0.95),  # L_hip
    12: (0.58, 0.55, 0.95),  # R_hip
}


def test_wrist_elevation_arms_hanging_returns_zero():
    """Wrists at hip level (hanging arms) must produce elevation = 0."""
    kp = _kp({**SHOULDERS_HIPS, 9: (0.38, 0.58, 0.92), 10: (0.62, 0.58, 0.92)})
    assert _wrist_elevation_magnitude(kp) == 0.0


def test_wrist_elevation_arms_at_shoulder_returns_zero():
    """Wrists at exactly shoulder height (T-pose) also yield 0."""
    kp = _kp({**SHOULDERS_HIPS, 9: (0.20, 0.30, 0.92), 10: (0.80, 0.30, 0.92)})
    assert _wrist_elevation_magnitude(kp) == 0.0


def test_wrist_elevation_one_arm_raised_fires():
    """One wrist above shoulder line should produce positive elevation."""
    # L wrist at y=0.05, shoulder y=0.30, torso_v=0.25 → elevation = 1.0
    kp = _kp({**SHOULDERS_HIPS, 9: (0.30, 0.05, 0.92), 10: (0.62, 0.58, 0.92)})
    assert _wrist_elevation_magnitude(kp) == pytest.approx(1.0, abs=0.01)


def test_wrist_elevation_saturates_at_1():
    """Wrist much higher than 1 torso-span above shoulders still clamps to 1.0."""
    kp = _kp({**SHOULDERS_HIPS, 9: (0.30, 0.00, 0.92), 10: (0.62, 0.58, 0.92)})
    val = _wrist_elevation_magnitude(kp)
    assert val == pytest.approx(1.0, abs=0.01)


def test_wrist_elevation_low_confidence_keypoint_returns_zero():
    """Wrist visible but below confidence floor must be ignored."""
    kp = _kp({**SHOULDERS_HIPS, 9: (0.30, 0.05, 0.40), 10: (0.62, 0.58, 0.40)})
    # Default floor 0.55 — both wrists at 0.40 are rejected → 0.
    assert _wrist_elevation_magnitude(kp) == 0.0


def test_wrist_elevation_lower_floor_admits_low_conf():
    """When confidence_floor is relaxed, low-conf wrist contributes."""
    kp = _kp({**SHOULDERS_HIPS, 9: (0.30, 0.05, 0.40), 10: (0.62, 0.58, 0.40)})
    val = _wrist_elevation_magnitude(kp, confidence_floor=0.30)
    assert val == pytest.approx(1.0, abs=0.01)


def test_wrist_elevation_missing_hip_returns_zero():
    """Hips are required for torso reference; missing hips → 0."""
    kp = _kp({k: v for k, v in SHOULDERS_HIPS.items() if k not in (11, 12)})
    kp[9] = (0.30, 0.05, 0.92)
    assert _wrist_elevation_magnitude(kp) == 0.0


def test_wrist_elevation_collapsed_torso_returns_zero():
    """Degenerate torso span (<0.02) cannot normalize — return 0."""
    kp = _kp({
        5: (0.40, 0.30, 0.95),
        6: (0.60, 0.30, 0.95),
        11: (0.42, 0.31, 0.95),  # hip almost coincident with shoulder
        12: (0.58, 0.31, 0.95),
        9: (0.30, 0.05, 0.92),
    })
    assert _wrist_elevation_magnitude(kp) == 0.0


def test_set_tuning_accepts_postural_knobs():
    """Hot-tune knobs must round-trip through set_tuning."""
    tracker = PersonSceneTracker(movement_source=MOVEMENT_SOURCE_ELEVATION_OR_VELOCITY)
    tracker.set_tuning(postural_confidence_floor=0.7, postural_ema_alpha=0.5)
    assert tracker.postural_confidence_floor == pytest.approx(0.7)
    assert tracker.postural_ema_alpha == pytest.approx(0.5)


def test_set_tuning_clamps_postural_knobs():
    """Out-of-range tune values are clamped to safe bounds."""
    tracker = PersonSceneTracker(movement_source=MOVEMENT_SOURCE_ELEVATION_OR_VELOCITY)
    tracker.set_tuning(postural_confidence_floor=2.5, postural_ema_alpha=0.0)
    assert tracker.postural_confidence_floor == pytest.approx(1.0)
    # alpha lower bound is 0.05 (avoid divide-by-near-zero / dead lag).
    assert tracker.postural_ema_alpha == pytest.approx(0.05)


def _obs(track_id: int, cx: float, cy: float, kp: dict) -> PersonObservation:
    """Build a PersonObservation with bbox surrounding (cx, cy)."""
    return PersonObservation(
        track_id=track_id,
        bbox_xyxy=(cx - 0.05, cy - 0.10, cx + 0.05, cy + 0.10),
        confidence=0.9,
        keypoints=kp,
    )


def test_elevation_or_velocity_silent_when_standing_still():
    """Standing still with arms hanging across many frames yields no movement."""
    tracker = PersonSceneTracker(
        movement_source=MOVEMENT_SOURCE_ELEVATION_OR_VELOCITY,
        stillness_deadband=0.03,
    )
    kp_hang = _kp({**SHOULDERS_HIPS, 9: (0.38, 0.58, 0.92), 10: (0.62, 0.58, 0.92)})
    obs = _obs(track_id=1, cx=0.5, cy=0.4, kp=kp_hang)
    last_movement = None
    for _ in range(10):
        scene = tracker.update([obs], frame_size=(640, 480), dt=0.2)
        last_movement = scene.tracks[0].movement
    assert last_movement == 0.0


def test_elevation_ema_smooths_postural_only_signal():
    """EMA dampens a single high-postural reading vs a sustained one.

    Tests the EMA mechanic directly: same raw input produces a smaller
    movement value on the first frame after a string of zeros than
    after a string of full-saturation frames. Single-frame postural
    spikes get dampened; sustained postural eventually saturates.
    The velocity component is held silent (no centroid jump, near-zero
    keypoint delta on the postural-only test).
    """
    tracker = PersonSceneTracker(
        movement_source=MOVEMENT_SOURCE_ELEVATION_OR_VELOCITY,
        stillness_deadband=0.0,
    )
    # First case: previous frames had wrists below shoulder (postural=0).
    # Then exact same keypoints repeated so velocity = 0. Postural spikes
    # to 1.0 raw; with alpha=0.35 the smoothed value is ~0.35.
    kp_hang = _kp({**SHOULDERS_HIPS, 9: (0.40, 0.32, 0.92), 10: (0.62, 0.58, 0.92)})
    kp_up = _kp({**SHOULDERS_HIPS, 9: (0.40, 0.00, 0.92), 10: (0.62, 0.58, 0.92)})
    for _ in range(4):
        tracker.update([_obs(1, 0.5, 0.4, kp_hang)], frame_size=(640, 480), dt=0.2)
    # Two consecutive identical raised frames — keypoint delta = 0, so
    # velocity = 0 and we read pure smoothed postural.
    tracker.update([_obs(1, 0.5, 0.4, kp_up)], frame_size=(640, 480), dt=0.2)
    first_raise = tracker.update([_obs(1, 0.5, 0.4, kp_up)], frame_size=(640, 480), dt=0.2)
    # After two raised frames with alpha=0.35 starting from ~0:
    # frame1 smoothed ≈ 0.35, frame2 smoothed ≈ 0.35*1 + 0.65*0.35 ≈ 0.5775
    assert 0.4 < first_raise.tracks[0].movement < 0.7


def test_elevation_or_velocity_sustained_raise_does_fire():
    """A sustained raise across multiple frames eventually saturates the EMA."""
    tracker = PersonSceneTracker(
        movement_source=MOVEMENT_SOURCE_ELEVATION_OR_VELOCITY,
        stillness_deadband=0.03,
    )
    kp_raised = _kp({**SHOULDERS_HIPS, 9: (0.30, 0.00, 0.92), 10: (0.62, 0.58, 0.92)})
    last = 0.0
    for _ in range(8):
        scene = tracker.update([_obs(1, 0.5, 0.4, kp_raised)], frame_size=(640, 480), dt=0.2)
        last = scene.tracks[0].movement
    assert last > 0.9  # within EMA convergence of saturation
