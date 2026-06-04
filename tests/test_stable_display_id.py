"""Stable display id (6/4 r19).

The raw ByteTrack id can churn 5-15 times in 30 seconds of motion as
the bbox shape shifts. Audio is insulated by the inheritance code, but
the preview overlay used to flash a new id every time. stable_id is
the persistent overlay id: assigned once when a track is first
allocated, carried through every inheritance hop, and stays with the
same physical person until they leave frame and the memory expires.
"""
from __future__ import annotations

import pytest

from audio.lisbon_swn_camera_bridge import (
    PersonObservation,
    PersonSceneTracker,
)


def _obs(track_id, bbox, conf=0.9):
    return PersonObservation(track_id=track_id, bbox_xyxy=bbox, confidence=conf)


def test_first_track_gets_stable_id_one():
    tracker = PersonSceneTracker()
    scene = tracker.update([_obs(1, (100, 100, 200, 400))], frame_size=(640, 480), dt=0.2)
    assert scene.tracks[0].stable_id == 1


def test_stable_id_persists_when_bytetrack_id_unchanged():
    tracker = PersonSceneTracker()
    tracker.update([_obs(1, (100, 100, 200, 400))], frame_size=(640, 480), dt=0.2)
    scene = tracker.update([_obs(1, (110, 100, 210, 400))], frame_size=(640, 480), dt=0.2)
    assert scene.tracks[0].stable_id == 1


def test_stable_id_carries_across_inheritance_when_bytetrack_changes_id():
    """ByteTrack frequently drops and re-issues ids during fast motion.
    The inheritance code reuses the orphan track's memory; stable_id
    must ride along so the overlay doesn't flash a new label.
    """
    tracker = PersonSceneTracker(match_threshold=0.5)
    tracker.update([_obs(1, (100, 100, 200, 400))], frame_size=(640, 480), dt=0.2)
    # Same person, ByteTrack assigns new id 99 — inheritance should
    # detect the centroid match and carry stable_id=1 over.
    scene = tracker.update([_obs(99, (108, 102, 208, 402))], frame_size=(640, 480), dt=0.2)
    assert len(scene.tracks) == 1
    assert scene.tracks[0].id == 99             # ByteTrack id changed
    assert scene.tracks[0].stable_id == 1       # stable id preserved


def test_separate_people_get_separate_stable_ids():
    tracker = PersonSceneTracker(match_threshold=0.2)
    scene = tracker.update(
        [_obs(1, (50, 100, 150, 400)), _obs(2, (450, 100, 550, 400))],
        frame_size=(640, 480), dt=0.2,
    )
    assert len(scene.tracks) == 2
    stable_ids = {t.stable_id for t in scene.tracks}
    assert stable_ids == {1, 2}


def test_stable_id_monotonic_across_many_allocations():
    """Three people walk through one at a time. stable_ids should be
    1, 2, 3 — strictly increasing, never reused."""
    tracker = PersonSceneTracker(max_missing=0, match_threshold=0.1)
    # Person 1
    s = tracker.update([_obs(1, (50, 100, 150, 400))], frame_size=(640, 480), dt=0.2)
    p1_stable = s.tracks[0].stable_id
    # Person 1 leaves
    tracker.update([], frame_size=(640, 480), dt=0.2)
    # Person 2 enters
    s = tracker.update([_obs(2, (450, 100, 550, 400))], frame_size=(640, 480), dt=0.2)
    p2_stable = s.tracks[0].stable_id
    # Person 2 leaves
    tracker.update([], frame_size=(640, 480), dt=0.2)
    # Person 3
    s = tracker.update([_obs(3, (300, 100, 400, 400))], frame_size=(640, 480), dt=0.2)
    p3_stable = s.tracks[0].stable_id
    assert p1_stable < p2_stable < p3_stable
