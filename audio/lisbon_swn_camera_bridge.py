#!/usr/bin/env python3
"""Lisbon SWN camera soundscape bridge.

Routes SWN/rack stereo returning on ES-9 inputs 1/2 to ES-9 outputs 1/2,
while sending slow DC CV to ES-9 physical 3.5 mm CV outputs 1-8
(CoreAudio outputs 9-16 by default).

The modulation source is the local Lisbon camera bridge (`/frame.jpg`). This is
intentionally simple and safe: no identity tracking, just brightness, motion, and
where the visual mass sits in the frame.
"""

from __future__ import annotations

import argparse
import io
import json
import math
import signal
import sys
import threading
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence

import numpy as np
from PIL import Image, ImageDraw

# Chord palette helpers — used by the slow-loop profile poller to interpolate
# between chords. Defensive import so the bridge still runs if the module
# isn't available (e.g. older deployments).
try:
    from audio.chord_palette import interpolate_chord, apply_chord_drift  # type: ignore
except Exception:
    try:
        from chord_palette import interpolate_chord, apply_chord_drift  # type: ignore
    except Exception:
        def interpolate_chord(from_chord, to_chord, *, elapsed_seconds):  # type: ignore
            return to_chord
        def apply_chord_drift(chord, *, drift_phase_seconds, **kwargs):  # type: ignore
            return chord


CV_LABELS = [
    "cv1_voice1_1v_oct",
    "cv2_voice2_1v_oct",
    "cv3_voice3_1v_oct",
    "cv4_wavetable_browse",
    "cv5_transpose",
    "cv6_main_mix_vca",
    "cv7_glitch_trigger",
    "cv8_depth",
]

# CV7 drives the O&C logic gate that gates pink noise into SWN dispersion_pattern.
# Conceptually a "glitch trigger" — sparse, gated by people-movement, used as spice.
GLITCH_TRIGGER_CV_INDEX = 6
MOVEMENT_GATE_CV_INDEX = GLITCH_TRIGGER_CV_INDEX  # back-compat alias
MAIN_MIX_VCA_CV_INDEX = 5  # cv6 -> Intellijel Quad VCA CV1

# Per-channel slew rates (Hz, 1-pole exp). Higher = snappier reaction.
# voices 1/2/3 stay glacial so V/oct doesn't pop; mix VCA + glitch react
# fast so movement feels responsive; timbral controls in between.
# Live tuning 2026-06-03:
#   - round 1: bumped mix VCA + glitch from global 6Hz default
#   - round 2: operator reports "vol is jumpy". Mix VCA at 18Hz was
#     tracking every YOLO bbox jitter. Dropped to 4Hz (~250ms tau) so
#     it averages out detection bounce while a normal walk still moves
#     volume noticeably. Glitch stays fast — it's supposed to be punchy.
PER_CV_SMOOTHING_HZ = [
    6.0,    # cv1 voice1 1v/oct  — chord pitch, slow
    6.0,    # cv2 voice2 1v/oct
    6.0,    # cv3 voice3 1v/oct
    10.0,   # cv4 wavetable browse
    6.0,    # cv5 transpose — slow bipolar V/oct shift (was 10Hz dispersion)
    6.0,    # cv6 main mix VCA   — CV-side slew (input is already low-passed)
    24.0,   # cv7 glitch trigger — fastest, gates pink noise
    10.0,   # cv8 depth
]
@dataclass(frozen=True)
class CameraFeatures:
    brightness: float
    motion: float
    centroid_x: float
    centroid_y: float


@dataclass(frozen=True)
class PersonObservation:
    """One raw person detection from YOLO/ByteTrack.

    `keypoints` is an optional dict {kpt_idx: (x_norm, y_norm, conf)} for
    pose-model detectors (yolo11n-pose etc). None for bbox-only models.
    Coordinates are normalised to [0,1] using the frame size at detect time.
    """

    track_id: int | None
    bbox_xyxy: tuple[float, float, float, float]
    confidence: float = 1.0
    keypoints: dict[int, tuple[float, float, float]] | None = None


@dataclass(frozen=True)
class PersonTrack:
    id: int
    bbox_xyxy: tuple[float, float, float, float]
    confidence: float
    center_x: float
    center_y: float
    width: float
    height: float
    area: float
    distance: float
    movement: float
    age: int
    # 6/4 r18: keypoints carried to renderers so the preview overlay can
    # draw a skeleton. None when the bridge is using a bbox-only detector.
    keypoints: dict[int, tuple[float, float, float]] | None = None
    # 6/4 r19: stable display id, assigned once per person and carried
    # across ByteTrack id churn via the inheritance path. The `id` field
    # mirrors the live ByteTrack id (memory dict key + YOLO coherence).
    # `stable_id` is what the preview overlay renders so humans can
    # follow one person across hundreds of YOLO id reassignments.
    stable_id: int = 0


@dataclass(frozen=True)
class PersonScene:
    people_count: int
    tracks: list[PersonTrack]
    centroid_x: float
    centroid_y: float
    spread_x: float
    nearest_distance: float
    mean_distance: float
    movement: float
    activity: float
    count_norm: float


@dataclass
class _TrackMemory:
    id: int
    center_x: float
    center_y: float
    bbox_xyxy: tuple[float, float, float, float]
    width: float
    height: float
    area: float
    distance: float
    age: int = 0
    missing: int = 0
    # 6/4 r17: pose keypoints from the previous frame. Used by the
    # pose-based movement source to compute max keypoint displacement.
    # None when the detector is bbox-only or no keypoints were confident.
    keypoints: dict[int, tuple[float, float, float]] | None = None
    # 6/4 r19: stable display id. Assigned at first allocation and
    # preserved across ByteTrack id churn — when inheritance moves
    # memory to a new ByteTrack key, the stable_id rides along.
    stable_id: int = 0
    # 6/5 r2: EMA-smoothed postural magnitude. Single-frame keypoint
    # noise can spike the raw postural signal momentarily above
    # threshold even when the person is still. Smoothing across frames
    # rejects 1-2 frame spikes while preserving genuine multi-frame
    # raises. Updated lazily — only the elevation/extension postural
    # branches touch this; bbox/pose-velocity branches leave it at 0.
    postural_ema: float = 0.0


# 6/4 r17: movement source selector.
#   "bbox"        — pre-existing behaviour (max planar/distance delta of the bbox)
#   "pose"        — yolo pose model max gesture-keypoint delta (velocity-like signal)
#   "pose_raise"  — postural: fires when wrist is above the matching elbow;
#                   magnitude scales with how far the wrist climbs past the elbow,
#                   saturating at ~shoulder height. Walking, dancing,
#                   fast motion all silent; arms up = glitch.
#   "bbox_raise"  — postural via bbox aspect ratio (height/width). Raising
#                   arms above the head dramatically increases the bbox
#                   height relative to width, going from ~1.5 standing to
#                   ~3.0 with arms up. Works on top-down camera mounts
#                   where pose keypoints are unreliable (the model is
#                   trained on standing front-views, not bird's-eye).
# Wired through PersonSceneTracker.set_tuning so the operator can flip
# live without a bridge restart.
MOVEMENT_SOURCE_BBOX = "bbox"
MOVEMENT_SOURCE_POSE = "pose"
MOVEMENT_SOURCE_POSE_RAISE = "pose_raise"
MOVEMENT_SOURCE_BBOX_RAISE = "bbox_raise"
MOVEMENT_SOURCE_ARM_EXTENSION = "arm_extension"
# 6/4 r24: combined "arm extension OR fast pose motion" — max of the
# two signals so a raised arm OR a fast wave both fire CV7.
MOVEMENT_SOURCE_EXTENSION_OR_VELOCITY = "extension_or_velocity"
# 6/5 r2: wrist-elevation postural source; replaces arm_extension as
# the recommended postural feature for non-top-down camera angles
# (see _wrist_elevation_magnitude docstring). Combined with velocity
# the same way extension_or_velocity does, gated by centroid continuity.
MOVEMENT_SOURCE_ELEVATION_OR_VELOCITY = "elevation_or_velocity"
_VALID_MOVEMENT_SOURCES = {
    MOVEMENT_SOURCE_BBOX,
    MOVEMENT_SOURCE_POSE,
    MOVEMENT_SOURCE_POSE_RAISE,
    MOVEMENT_SOURCE_BBOX_RAISE,
    MOVEMENT_SOURCE_ARM_EXTENSION,
    MOVEMENT_SOURCE_EXTENSION_OR_VELOCITY,
    MOVEMENT_SOURCE_ELEVATION_OR_VELOCITY,
}

# Keypoints we trust for "gesture" motion. Hands, feet, head, and elbows.
# Skip the torso (shoulders/hips) because they barely translate during a
# wave; skip eyes/ears because head-pose noise dominates the small motion.
# 6/4 r19: added elbows (7, 8) — they have rock-solid confidence and the
# elbow swings further than the wrist during a hand-raise (rotation point
# is the shoulder, so elbow has a bigger arc). Adding them dramatically
# improves arm-raise / wave detection.
# Reference: ultralytics COCO-17 keypoint ordering.
_GESTURE_KEYPOINTS = {0, 7, 8, 9, 10, 15, 16}  # nose, L/R elbow, L/R wrist, L/R ankle
# 6/4 r19: keypoints below this drop out (especially ankles when the
# camera is mounted high and feet leave frame). Lowering from 0.4 to
# 0.3 catches more ankle frames without admitting hallucinations.
_KEYPOINT_MIN_CONFIDENCE = 0.3

# 6/5 r1: centroid-teleport guard for velocity computations. When ByteTrack
# reuses an id across people, or orphan-inheritance carries memory from a
# different track, the resulting `previous` → current keypoint delta is a
# cross-identity comparison that fakes a huge velocity and fires CV7 with
# no real movement. Real walking/jumping at 5Hz keeps centroid jumps below
# ~0.20 frame-units; observed swap-events in the trace were 0.55-0.59. A
# threshold of 0.25 cleanly separates them. Postural sources (arm
# extension, raise) are per-frame and unaffected by this gate.
_CENTROID_TELEPORT_THRESHOLD = 0.25


def _max_keypoint_delta(
    previous: dict[int, tuple[float, float, float]],
    current: dict[int, tuple[float, float, float]],
) -> float:
    """Maximum positional delta across confident gesture keypoints.

    Inputs are dicts of {kpt_idx: (x_norm, y_norm, conf)}. Only keypoints
    in _GESTURE_KEYPOINTS that appear in both frames with conf above
    _KEYPOINT_MIN_CONFIDENCE contribute. Returns 0.0 when no shared
    confident keypoints — caller falls back to bbox delta.
    """
    best = 0.0
    for kpt_idx in _GESTURE_KEYPOINTS:
        if kpt_idx not in previous or kpt_idx not in current:
            continue
        px, py, pc = previous[kpt_idx]
        cx, cy, cc = current[kpt_idx]
        if pc < _KEYPOINT_MIN_CONFIDENCE or cc < _KEYPOINT_MIN_CONFIDENCE:
            continue
        delta = math.hypot(cx - px, cy - py)
        if delta > best:
            best = delta
    return best


# 6/4 r20: pose_raise — postural trigger. When the wrist (kp 9 or 10)
# rises above the matching elbow (kp 7 or 8), the gesture fires. Image
# coordinates have y=0 at the top, so "wrist above elbow" means
# wrist_y < elbow_y. We scale the elevation by RAISE_SATURATION_NORM so
# a wrist roughly at shoulder height (typical comfortable raise) hits
# 1.0. Saturation = 0.15 of frame height ≈ upper-arm length in normal
# camera framing. Tweak via cv7_glitch_threshold if needed; this is a
# 0..1 signal flowing through the same latch + threshold pipeline.
_RAISE_SATURATION_NORM = 0.15

# Arm pairs as (wrist_idx, elbow_idx) — checked independently, signal
# is the max of the two arms.
_RAISE_ARMS = ((9, 7), (10, 8))  # (L_wrist, L_elbow), (R_wrist, R_elbow)


def _raise_magnitude(
    keypoints: dict[int, tuple[float, float, float]] | None,
) -> float:
    """Compute "arms raised" magnitude from a single frame's keypoints.

    Returns max of (elbow_y - wrist_y) / _RAISE_SATURATION_NORM across
    both arms, clamped to 0..1. Requires both wrist and elbow to be
    confident; if either falls below _KEYPOINT_MIN_CONFIDENCE the arm
    is skipped. Returns 0.0 when no arm qualifies.

    6/4 r21 — guards against head-only detections: a person cropped to
    just their head/shoulders at the top of the frame can have YOLO
    pose hallucinate "elbow" and "wrist" keypoints all clustered in
    the top 10% of frame. The elbow→wrist delta is tiny but technically
    above zero, producing phantom fires. We reject any arm where BOTH
    elbow and wrist sit above frame y=0.10 (top 10%), which is the
    region where a real person's elbows/wrists almost never appear.

    Unlike _max_keypoint_delta this is a POSITION signal, not a velocity
    signal — wrist held above elbow continues to read non-zero across
    frames, so the CV7 latch holds full max_cv for the entire raise.
    Dropping the arms lets the signal decay to 0 immediately on the
    next frame, then the existing exponential release timer takes over.
    """
    if not keypoints:
        return 0.0
    best = 0.0
    for wrist_idx, elbow_idx in _RAISE_ARMS:
        if wrist_idx not in keypoints or elbow_idx not in keypoints:
            continue
        wx, wy, wc = keypoints[wrist_idx]
        ex, ey, ec = keypoints[elbow_idx]
        if wc < _KEYPOINT_MIN_CONFIDENCE or ec < _KEYPOINT_MIN_CONFIDENCE:
            continue
        # Elevation: how far the wrist sits above the elbow in image
        # coords. Positive when raised, negative or zero when arm hangs.
        elevation = ey - wy
        if elevation <= 0.0:
            continue
        magnitude = elevation / _RAISE_SATURATION_NORM
        if magnitude > best:
            best = magnitude
    return min(1.0, best)


# 6/4 r22: bbox aspect ratio thresholds for the bbox_raise source.
# Standing person bbox aspect (h/w): typically 1.5-2.5 depending on
# pose. Raising both arms above the head pushes it to 2.8-3.5+ because
# the bbox extends up to the wrists. We saturate at 3.2 so a clear
# arms-up reading fires full max_cv; below 2.0 nothing fires; between
# 2.0 and 3.2 the magnitude scales linearly.
_BBOX_RAISE_BASELINE = 2.0   # below this = no raise
_BBOX_RAISE_SATURATION = 3.2  # at or above this = full signal


def _bbox_raise_magnitude(width: float, height: float) -> float:
    """Compute "arms raised" magnitude from bbox aspect ratio.

    Returns (height/width - BASELINE) / (SATURATION - BASELINE),
    clamped to 0..1. Width = 0 (degenerate bbox) returns 0.

    Why bbox aspect works for top-down installs: the pose model is
    trained on standing front-views and produces near-random keypoint
    positions on a bird's-eye foreshortened person. But the bbox
    itself stays meaningful — extending arms above the head still
    extends the vertical extent of the visible silhouette, just at
    a different angle. Aspect ratio is a postural signal that does
    not depend on per-joint model accuracy.
    """
    if width <= 1e-6:
        return 0.0
    aspect = height / width
    if aspect <= _BBOX_RAISE_BASELINE:
        return 0.0
    scaled = (aspect - _BBOX_RAISE_BASELINE) / (_BBOX_RAISE_SATURATION - _BBOX_RAISE_BASELINE)
    return min(1.0, scaled)


# 6/4 r23: top-down "arm extension" source. From a bird's-eye camera
# the standard "wrist above elbow" check fails because vertical
# motion in 3D collapses to ~0 motion in the image plane. But arm
# EXTENSION is preserved: when arms hang at the sides, wrists sit
# close to the shoulder line (distance ~= forearm length viewed
# vertically, projected ~0). When arms reach out or up, wrists move
# away from the shoulder line in image space.
#
# Signal = max wrist-to-shoulder-midpoint distance / torso reference
# length, across both arms. Torso reference = shoulder-to-hip distance
# in image, normalised by frame diagonal. Saturates when wrist is at
# ~1.5x torso length from shoulder midpoint (a fully extended arm).
_EXTENSION_SATURATION = 1.5


def _arm_extension_magnitude(
    keypoints: dict[int, tuple[float, float, float]] | None,
) -> float:
    """Max wrist-to-shoulder-midpoint distance / torso length.

    Works on top-down camera installs because the metric is image-plane
    distance from a stable anatomical reference (shoulder midpoint),
    NOT vertical position which collapses under foreshortening.

    Returns 0.0 when keypoints are missing, low confidence, or when
    the torso reference can't be established. Saturates at 1.0 when
    a wrist is ~1.5 torso-lengths from the shoulder line.
    """
    if not keypoints:
        return 0.0
    # Need shoulders + hips for the torso reference.
    l_shldr = keypoints.get(5)
    r_shldr = keypoints.get(6)
    l_hip = keypoints.get(11)
    r_hip = keypoints.get(12)
    if not (l_shldr and r_shldr):
        return 0.0
    if l_shldr[2] < _KEYPOINT_MIN_CONFIDENCE or r_shldr[2] < _KEYPOINT_MIN_CONFIDENCE:
        return 0.0
    shldr_mid_x = (l_shldr[0] + r_shldr[0]) * 0.5
    shldr_mid_y = (l_shldr[1] + r_shldr[1]) * 0.5
    # Torso reference: shoulder-mid to hip-mid distance. Fall back to
    # inter-shoulder width when hips are unreliable (top-down view
    # often loses hip confidence first).
    torso_len = 0.0
    if l_hip and r_hip and l_hip[2] >= _KEYPOINT_MIN_CONFIDENCE and r_hip[2] >= _KEYPOINT_MIN_CONFIDENCE:
        hip_mid_x = (l_hip[0] + r_hip[0]) * 0.5
        hip_mid_y = (l_hip[1] + r_hip[1]) * 0.5
        torso_len = math.hypot(hip_mid_x - shldr_mid_x, hip_mid_y - shldr_mid_y)
    if torso_len < 0.02:
        # Degenerate torso (top-down with body collapsed onto self) —
        # use inter-shoulder width as the reference instead.
        torso_len = math.hypot(r_shldr[0] - l_shldr[0], r_shldr[1] - l_shldr[1])
    if torso_len < 0.02:
        return 0.0
    # Check each wrist's distance from the shoulder midpoint.
    best = 0.0
    for wrist_idx in (9, 10):
        wrist = keypoints.get(wrist_idx)
        if not wrist or wrist[2] < _KEYPOINT_MIN_CONFIDENCE:
            continue
        dist = math.hypot(wrist[0] - shldr_mid_x, wrist[1] - shldr_mid_y)
        normalised = dist / torso_len
        if normalised > best:
            best = normalised
    return min(1.0, best / _EXTENSION_SATURATION)


# 6/5 r2: wrist-elevation postural source. arm_extension's geometry
# (wrist→shoulder distance / torso-len ratio) overshoots on
# foreshortened bodies — at oblique camera angles the torso projects
# SHORT while hanging arms still project the full forearm distance
# from shoulders. Result: standing still reads 0.4-0.8 just from
# anatomy, well above any sane fire threshold.
#
# This source uses VERTICAL DISPLACEMENT IN IMAGE COORDS as the signal,
# which is sign-correct across all camera angles where the camera is
# above eye level:
#   - hanging arm: wrist projects BELOW shoulder in image (y > shoulder_y)
#   - raised arm:  wrist projects ABOVE shoulder in image (y < shoulder_y)
# We compute (shoulder_y - wrist_y) / torso_vertical_extent, clamped to
# [0, 1]. Hanging arms yield negative elevation → 0. Raised arms yield
# positive elevation → fire.
#
# Robustness: requires a stricter confidence floor than arm_extension
# (default 0.55 vs 0.30) because postural false positives kill the
# install far worse than missed gestures. The threshold is wired
# through tune.json as `postural_confidence_floor`.
_WRIST_ELEVATION_DEFAULT_CONF_FLOOR = 0.55


def _wrist_elevation_magnitude(
    keypoints: dict[int, tuple[float, float, float]] | None,
    confidence_floor: float = _WRIST_ELEVATION_DEFAULT_CONF_FLOOR,
) -> float:
    """Vertical wrist-above-shoulder elevation / torso vertical span.

    Returns 0.0 when:
      - keypoints missing
      - any required keypoint (both shoulders, both hips, the candidate
        wrist) below `confidence_floor`
      - both wrists hang at or below the shoulder line
      - torso vertical span degenerates (<0.02 frame-units)

    Image-coordinate sign convention: y=0 is the TOP of the frame.
    A wrist with smaller y is HIGHER in image space, which corresponds
    to a raised arm at any camera angle where the camera is above the
    subject's eye line. Saturates at 1.0 when a wrist is one full
    torso-vertical-span above the shoulder line.
    """
    if not keypoints:
        return 0.0
    l_shldr = keypoints.get(5)
    r_shldr = keypoints.get(6)
    l_hip = keypoints.get(11)
    r_hip = keypoints.get(12)
    if not (l_shldr and r_shldr and l_hip and r_hip):
        return 0.0
    if (l_shldr[2] < confidence_floor or r_shldr[2] < confidence_floor or
            l_hip[2] < confidence_floor or r_hip[2] < confidence_floor):
        return 0.0
    shldr_mid_y = (l_shldr[1] + r_shldr[1]) * 0.5
    hip_mid_y = (l_hip[1] + r_hip[1]) * 0.5
    torso_v = abs(hip_mid_y - shldr_mid_y)
    if torso_v < 0.02:
        return 0.0
    best = 0.0
    for wrist_idx in (9, 10):
        wrist = keypoints.get(wrist_idx)
        if not wrist or wrist[2] < confidence_floor:
            continue
        # y increases downward in image coords, so wrist ABOVE shoulder
        # means shoulder_y - wrist_y > 0.
        elevation = (shldr_mid_y - wrist[1]) / torso_v
        if elevation > best:
            best = elevation
    return min(1.0, best)


class PersonSceneTracker:
    """Stable ID and scene summary layer for person detections.

    Ultralytics/ByteTrack supplies IDs when it can. When it cannot, this class
    does conservative nearest-centroid matching so the musical voices do not
    randomly reassign every frame.
    """

    def __init__(self, max_missing: int = 8, match_threshold: float = 0.24, stillness_deadband: float = 0.03, movement_source: str = MOVEMENT_SOURCE_BBOX) -> None:
        self.max_missing = max(0, int(max_missing))
        self.match_threshold = float(match_threshold)
        self.stillness_deadband = max(0.0, float(stillness_deadband))
        if movement_source not in _VALID_MOVEMENT_SOURCES:
            raise ValueError(f"movement_source must be one of {sorted(_VALID_MOVEMENT_SOURCES)}, got {movement_source!r}")
        self.movement_source = movement_source
        # 6/5 r2: hot-tunable postural knobs.
        # postural_confidence_floor — min keypoint confidence required
        # for elevation/extension postural sources to use a keypoint.
        # Default raised from the legacy 0.30 to 0.55: postural false
        # positives kill the install far worse than missed gestures.
        # postural_ema_alpha — weight of the current frame in the
        # exponential moving average. 1.0 = no smoothing; lower values
        # introduce latency but reject single-frame keypoint noise.
        # 0.35 → ~3-frame effective window at 5Hz camera = ~600ms.
        self.postural_confidence_floor: float = _WRIST_ELEVATION_DEFAULT_CONF_FLOOR
        self.postural_ema_alpha: float = 0.35
        self._tracks: dict[int, _TrackMemory] = {}
        self._next_id = 1
        # 6/4 r19: stable display ids — issued once per person, carried
        # through ByteTrack id churn. Monotonically increasing so the
        # operator can recognise "id 3" as the same person 5 minutes later.
        self._next_stable_id = 1

    def set_tuning(self, *, stillness_deadband: float | None = None, match_threshold: float | None = None, movement_source: str | None = None, postural_confidence_floor: float | None = None, postural_ema_alpha: float | None = None) -> None:
        """Hot-update detector thresholds from the profile poller.

        Operator 6/4 r13: source-PR-per-knob was costing ~10s of CV freeze
        per tweak. The bridge already polls heuristic_profile.json every
        second; expose the most-tweaked knobs through that path so
        threshold tuning is zero-restart.

        Only updates fields whose new value differs meaningfully from the
        current value (>1e-6) so a no-op poll doesn't log noise.
        """
        if stillness_deadband is not None:
            new_val = max(0.0, float(stillness_deadband))
            if abs(new_val - self.stillness_deadband) > 1e-6:
                print(f"[poll-tune] stillness_deadband {self.stillness_deadband:.4f} -> {new_val:.4f}", flush=True)
                self.stillness_deadband = new_val
        if match_threshold is not None:
            new_val = float(match_threshold)
            if abs(new_val - self.match_threshold) > 1e-6:
                print(f"[poll-tune] match_threshold {self.match_threshold:.4f} -> {new_val:.4f}", flush=True)
                self.match_threshold = new_val
        if movement_source is not None:
            new_val = str(movement_source).lower().strip()
            if new_val not in _VALID_MOVEMENT_SOURCES:
                print(f"[poll-tune] movement_source {new_val!r} ignored — valid values: {sorted(_VALID_MOVEMENT_SOURCES)}", flush=True)
            elif new_val != self.movement_source:
                print(f"[poll-tune] movement_source {self.movement_source!r} -> {new_val!r}", flush=True)
                self.movement_source = new_val
        if postural_confidence_floor is not None:
            new_val = max(0.0, min(1.0, float(postural_confidence_floor)))
            if abs(new_val - self.postural_confidence_floor) > 1e-6:
                print(f"[poll-tune] postural_confidence_floor {self.postural_confidence_floor:.3f} -> {new_val:.3f}", flush=True)
                self.postural_confidence_floor = new_val
        if postural_ema_alpha is not None:
            new_val = max(0.05, min(1.0, float(postural_ema_alpha)))
            if abs(new_val - self.postural_ema_alpha) > 1e-6:
                print(f"[poll-tune] postural_ema_alpha {self.postural_ema_alpha:.3f} -> {new_val:.3f}", flush=True)
                self.postural_ema_alpha = new_val

    def update(
        self,
        observations: Sequence[PersonObservation],
        *,
        frame_size: tuple[int, int],
        dt: float,
    ) -> PersonScene:
        frame_w, frame_h = frame_size
        frame_w = max(1, int(frame_w))
        frame_h = max(1, int(frame_h))
        dt = max(1e-3, float(dt))

        active_ids: set[int] = set()
        active_tracks: list[PersonTrack] = []

        for obs in observations:
            metrics = self._observation_metrics(obs, frame_w, frame_h)
            # 6/4 r12: when ByteTrack assigns an id we've never seen, try
            # to inherit state from any nearby orphan track first. Without
            # this, ByteTrack id churn (new id every few frames at dim
            # range) makes EVERY new observation hit the "previous is
            # None → movement = 0" path. We never see movement on the
            # actual person because no single id persists long enough.
            #
            # The match is by centroid distance to any non-active track in
            # _TrackMemory; if within match_threshold we re-use that track's
            # state (renamed to the new ByteTrack id so the dict stays
            # coherent with ByteTrack's view). Otherwise allocate a fresh
            # row as before.
            if obs.track_id is not None:
                yolo_id = int(obs.track_id)
                if yolo_id not in self._tracks:
                    inherited_id = self._match_or_allocate(metrics["center_x"], metrics["center_y"], active_ids)
                    if inherited_id != yolo_id and inherited_id in self._tracks:
                        # Carry the orphan's memory under the new ByteTrack id
                        self._tracks[yolo_id] = self._tracks.pop(inherited_id)
                        self._tracks[yolo_id].id = yolo_id
                track_id = yolo_id
            else:
                track_id = self._match_or_allocate(metrics["center_x"], metrics["center_y"], active_ids)
            previous = self._tracks.get(track_id)
            # 6/4 r19: resolve the stable display id. If we have a previous
            # memory (either from existing ByteTrack id OR via inheritance
            # in the block above), we keep its stable_id. Brand-new tracks
            # get a fresh stable id from the monotonic counter.
            if previous is not None and previous.stable_id:
                stable_id = previous.stable_id
            else:
                stable_id = self._next_stable_id
                self._next_stable_id += 1
            # 6/4 r17/r20/r21/r22: movement source is selectable.
            #   POSE         — velocity (max keypoint delta / dt)  REQUIRES previous frame
            #   POSE_RAISE   — postural via keypoints (wrist-above-elbow)  NO previous needed
            #   BBOX_RAISE   — postural via bbox aspect (h/w)  NO previous needed
            #   BBOX         — velocity (planar+distance delta / dt)  REQUIRES previous frame
            #
            # Postural sources compute the signal purely from the current
            # frame; ByteTrack id churn during motion produces frequent
            # first-frame allocations that would otherwise mute these.
            #
            # 6/5 r2: elevation_or_velocity branch sets this; all other
            # branches leave it 0 so _TrackMemory.postural_ema stays
            # bounded and switching modes mid-session is safe.
            next_postural_ema: float = 0.0
            if self.movement_source == MOVEMENT_SOURCE_POSE_RAISE and obs.keypoints is not None:
                raise_mag = _raise_magnitude(obs.keypoints)
                if raise_mag <= self.stillness_deadband:
                    movement = 0.0
                else:
                    movement = float(raise_mag)
                age = previous.age + 1 if previous is not None else 1
            elif self.movement_source == MOVEMENT_SOURCE_BBOX_RAISE:
                # Compute aspect ratio from RAW pixel bbox (not the
                # normalized-to-frame metrics["width"]/["height"] which
                # distort when frame is not square). x2-x1 and y2-y1
                # are pixel dimensions of the bbox.
                x1, y1, x2, y2 = obs.bbox_xyxy
                bbox_w_px = abs(float(x2) - float(x1))
                bbox_h_px = abs(float(y2) - float(y1))
                raise_mag = _bbox_raise_magnitude(bbox_w_px, bbox_h_px)
                if raise_mag <= self.stillness_deadband:
                    movement = 0.0
                else:
                    movement = float(raise_mag)
                age = previous.age + 1 if previous is not None else 1
            elif self.movement_source == MOVEMENT_SOURCE_ARM_EXTENSION and obs.keypoints is not None:
                raise_mag = _arm_extension_magnitude(obs.keypoints)
                if raise_mag <= self.stillness_deadband:
                    movement = 0.0
                else:
                    movement = float(raise_mag)
                age = previous.age + 1 if previous is not None else 1
            elif self.movement_source == MOVEMENT_SOURCE_EXTENSION_OR_VELOCITY:
                # 6/4 r24: posture (arm extension) OR fast pose motion.
                # Postural signal works on frame 1; velocity needs previous.
                # Output is max of the two so either path fires.
                postural = (
                    _arm_extension_magnitude(obs.keypoints)
                    if obs.keypoints is not None else 0.0
                )
                velocity = 0.0
                if previous is not None and obs.keypoints is not None and previous.keypoints is not None:
                    # 6/5 r1: gate velocity on centroid continuity. See
                    # _CENTROID_TELEPORT_THRESHOLD docstring — without
                    # this guard, identity swaps in the tracker compute
                    # spurious keypoint deltas that fire CV7 randomly.
                    centroid_jump = math.hypot(
                        metrics["center_x"] - previous.center_x,
                        metrics["center_y"] - previous.center_y,
                    )
                    if centroid_jump <= _CENTROID_TELEPORT_THRESHOLD:
                        delta = _max_keypoint_delta(previous.keypoints, obs.keypoints)
                        if delta > self.stillness_deadband:
                            velocity = _clamp01(delta / max(0.03, dt * 0.65))
                combined = max(postural, velocity)
                if combined <= self.stillness_deadband:
                    movement = 0.0
                else:
                    movement = float(combined)
                age = previous.age + 1 if previous is not None else 1
            elif self.movement_source == MOVEMENT_SOURCE_ELEVATION_OR_VELOCITY:
                # 6/5 r2: wrist-elevation (sign-correct postural) OR fast
                # pose motion. Replaces extension_or_velocity for camera
                # rigs where the torso is foreshortened — the elevation
                # feature uses image-y comparison instead of distance
                # ratios, so it does not over-trigger on standing-still
                # body geometry. Combined with EMA smoothing (state
                # carried on _TrackMemory.postural_ema) to reject
                # single-frame keypoint noise that arm_extension was
                # vulnerable to.
                raw_postural = (
                    _wrist_elevation_magnitude(obs.keypoints, self.postural_confidence_floor)
                    if obs.keypoints is not None else 0.0
                )
                # EMA: smoothed = alpha * raw + (1-alpha) * prev_smoothed.
                # First frame seeds with the raw value to avoid a slow
                # ramp from 0 on a person who is already mid-gesture
                # when the track first appears.
                alpha = self.postural_ema_alpha
                if previous is not None:
                    smoothed_postural = alpha * raw_postural + (1.0 - alpha) * previous.postural_ema
                else:
                    smoothed_postural = raw_postural
                next_postural_ema = float(smoothed_postural)
                velocity = 0.0
                if previous is not None and obs.keypoints is not None and previous.keypoints is not None:
                    centroid_jump = math.hypot(
                        metrics["center_x"] - previous.center_x,
                        metrics["center_y"] - previous.center_y,
                    )
                    if centroid_jump <= _CENTROID_TELEPORT_THRESHOLD:
                        delta = _max_keypoint_delta(previous.keypoints, obs.keypoints)
                        if delta > self.stillness_deadband:
                            velocity = _clamp01(delta / max(0.03, dt * 0.65))
                combined = max(smoothed_postural, velocity)
                if combined <= self.stillness_deadband:
                    movement = 0.0
                else:
                    movement = float(combined)
                age = previous.age + 1 if previous is not None else 1
            elif previous is None:
                movement = 0.0
                age = 1
            else:
                use_pose = (
                    self.movement_source == MOVEMENT_SOURCE_POSE
                    and obs.keypoints is not None
                    and previous.keypoints is not None
                )
                if use_pose:
                    assert obs.keypoints is not None and previous.keypoints is not None
                    delta = _max_keypoint_delta(previous.keypoints, obs.keypoints)
                    if delta == 0.0:
                        # No shared confident keypoints (e.g. person turned
                        # away, occluded limbs) — fall back to bbox signal
                        # so we don't silently mute movement.
                        planar_delta = math.hypot(metrics["center_x"] - previous.center_x, metrics["center_y"] - previous.center_y)
                        distance_delta = abs(metrics["distance"] - previous.distance)
                        delta = max(planar_delta, distance_delta)
                else:
                    # 6/4 r11: composite = max(planar_delta, distance_delta).
                    # Walking toward camera shows up in distance even when
                    # planar barely shifts.
                    planar_delta = math.hypot(metrics["center_x"] - previous.center_x, metrics["center_y"] - previous.center_y)
                    distance_delta = abs(metrics["distance"] - previous.distance)
                    delta = max(planar_delta, distance_delta)
                if delta <= self.stillness_deadband:
                    # Below deadband — gate movement signal to absorb YOLO
                    # bbox jitter, but always advance position metrics (see
                    # 6/4 r10) so cumulative drift across sub-deadband frames
                    # eventually fires when it exceeds the threshold.
                    movement = 0.0
                else:
                    movement = _clamp01(delta / max(0.03, dt * 0.65))
                age = previous.age + 1

            self._tracks[track_id] = _TrackMemory(
                id=track_id,
                center_x=metrics["center_x"],
                center_y=metrics["center_y"],
                bbox_xyxy=obs.bbox_xyxy,
                width=metrics["width"],
                height=metrics["height"],
                area=metrics["area"],
                distance=metrics["distance"],
                age=age,
                missing=0,
                keypoints=obs.keypoints,
                stable_id=stable_id,
                postural_ema=next_postural_ema,
            )
            active_ids.add(track_id)
            active_tracks.append(
                PersonTrack(
                    id=track_id,
                    bbox_xyxy=obs.bbox_xyxy,
                    confidence=float(obs.confidence),
                    center_x=metrics["center_x"],
                    center_y=metrics["center_y"],
                    width=metrics["width"],
                    height=metrics["height"],
                    area=metrics["area"],
                    distance=metrics["distance"],
                    movement=movement,
                    age=age,
                    keypoints=obs.keypoints,
                    stable_id=stable_id,
                )
            )

        for track_id, memory in list(self._tracks.items()):
            if track_id not in active_ids:
                memory.missing += 1
                if memory.missing > self.max_missing:
                    del self._tracks[track_id]

        active_tracks.sort(key=lambda t: t.id)
        return self._summarize(active_tracks)

    def _match_or_allocate(self, center_x: float, center_y: float, active_ids: set[int]) -> int:
        best_id: int | None = None
        best_dist = float("inf")
        for track_id, memory in self._tracks.items():
            if track_id in active_ids:
                continue
            dist = math.hypot(center_x - memory.center_x, center_y - memory.center_y)
            if dist < best_dist:
                best_dist = dist
                best_id = track_id
        if best_id is not None and best_dist <= self.match_threshold:
            return best_id
        while self._next_id in self._tracks or self._next_id in active_ids:
            self._next_id += 1
        allocated = self._next_id
        self._next_id += 1
        return allocated

    @staticmethod
    def _observation_metrics(obs: PersonObservation, frame_w: int, frame_h: int) -> dict[str, float]:
        x1, y1, x2, y2 = obs.bbox_xyxy
        x1, x2 = sorted((float(x1), float(x2)))
        y1, y2 = sorted((float(y1), float(y2)))
        x1 = float(np.clip(x1, 0, frame_w))
        x2 = float(np.clip(x2, 0, frame_w))
        y1 = float(np.clip(y1, 0, frame_h))
        y2 = float(np.clip(y2, 0, frame_h))
        width = _clamp01((x2 - x1) / frame_w)
        height = _clamp01((y2 - y1) / frame_h)
        area = _clamp01(width * height)
        center_x = _clamp01(((x1 + x2) * 0.5) / frame_w)
        center_y = _clamp01(((y1 + y2) * 0.5) / frame_h)
        bottom_y = _clamp01(y2 / frame_h)
        # Webcam-only distance proxy: a person walking from across the room
        # to right at the camera should sweep distance from ~0.05 to ~0.95.
        # Live test 6/3 round 5: original area 0.02..0.30 window was too
        # wide — realistic "close" is area ~0.10-0.15, so distance was only
        # reaching ~0.65 in practice. Tightened window to 0.02..0.12 so
        # standing ~1m from the camera saturates near 0.95.
        # Reference points from the Anker C200 in Lisbon space:
        #   far  (~4m): area ~ 0.02-0.04
        #   mid  (~2m): area ~ 0.06-0.08
        #   near (~1m): area ~ 0.10-0.12 (saturation)
        #   close (~0.5m): clipped at 0.95
        area_norm = _clamp01((area - 0.02) / (0.12 - 0.02))
        distance = _clamp01(0.05 + 0.90 * (area_norm ** 0.7))
        return {
            "width": width,
            "height": height,
            "area": area,
            "center_x": center_x,
            "center_y": center_y,
            "distance": distance,
        }

    @staticmethod
    def _summarize(tracks: Sequence[PersonTrack]) -> PersonScene:
        if not tracks:
            return PersonScene(
                people_count=0,
                tracks=[],
                centroid_x=0.5,
                centroid_y=0.5,
                spread_x=0.0,
                nearest_distance=0.0,
                mean_distance=0.0,
                movement=0.0,
                activity=0.0,
                count_norm=0.0,
            )

        weights = np.array([max(0.02, t.area * t.confidence) for t in tracks], dtype=np.float32)
        centers_x = np.array([t.center_x for t in tracks], dtype=np.float32)
        centers_y = np.array([t.center_y for t in tracks], dtype=np.float32)
        distances = np.array([t.distance for t in tracks], dtype=np.float32)
        movements = np.array([t.movement for t in tracks], dtype=np.float32)
        centroid_x = float(np.average(centers_x, weights=weights))
        centroid_y = float(np.average(centers_y, weights=weights))
        spread_x = float(np.max(centers_x) - np.min(centers_x)) if len(tracks) > 1 else 0.0
        nearest = float(np.max(distances))
        mean_distance = float(np.average(distances, weights=weights))
        # 6/5 r4: scene movement is the MAX across tracks, not weighted
        # average. A single person raising an arm in a room of 3 tracks
        # (one real, two phantoms with movement=0) should fire CV7. The
        # legacy weighted-average semantics diluted real gestures by the
        # phantom count, producing apparent "latency" and "intermittent
        # fires" that were actually threshold-narrow misses.
        movement = float(np.max(movements)) if len(movements) > 0 else 0.0
        count_norm = _clamp01(len(tracks) / 4.0)
        activity = _clamp01(movement * (0.86 + 0.10 * spread_x + 0.04 * count_norm))
        return PersonScene(
            people_count=len(tracks),
            tracks=list(tracks),
            centroid_x=_clamp01(centroid_x),
            centroid_y=_clamp01(centroid_y),
            spread_x=_clamp01(spread_x),
            nearest_distance=_clamp01(nearest),
            mean_distance=_clamp01(mean_distance),
            movement=_clamp01(movement),
            activity=activity,
            count_norm=count_norm,
        )


def quiet_person_scene(scene: PersonScene) -> PersonScene:
    """Return the same scene geometry with motion/activity zeroed for still frames."""

    return PersonScene(
        people_count=scene.people_count,
        tracks=[
            PersonTrack(
                id=track.id,
                bbox_xyxy=track.bbox_xyxy,
                confidence=track.confidence,
                center_x=track.center_x,
                center_y=track.center_y,
                width=track.width,
                height=track.height,
                area=track.area,
                distance=track.distance,
                movement=0.0,
                age=track.age,
                keypoints=track.keypoints,
                stable_id=track.stable_id,
            )
            for track in scene.tracks
        ],
        centroid_x=scene.centroid_x,
        centroid_y=scene.centroid_y,
        spread_x=scene.spread_x,
        nearest_distance=scene.nearest_distance,
        mean_distance=scene.mean_distance,
        movement=0.0,
        activity=0.0,
        count_norm=scene.count_norm,
    )


def hold_person_cv_for_still_frame(
    features: CameraFeatures,
    scene: PersonScene,
    *,
    frame_motion_threshold: float = 0.015,
) -> bool:
    """Suppress person-CV updates when frame differencing says the room is still.

    YOLO/ByteTrack boxes can jitter or split a stationary person into nearby tracks.
    The aggregate frame-difference motion is a better guardrail for "nobody moved".
    """

    return scene.people_count > 0 and _clamp01(features.motion) < max(0.0, float(frame_motion_threshold))


def _to_numpy(value: Any) -> np.ndarray | None:
    if value is None:
        return None
    if hasattr(value, "detach"):
        value = value.detach()
    if hasattr(value, "cpu"):
        value = value.cpu()
    if hasattr(value, "numpy"):
        value = value.numpy()
    return np.asarray(value)


def observations_from_yolo_result(
    result: Any,
    *,
    min_confidence: float = 0.35,
    frame_size: tuple[int, int] | None = None,
) -> list[PersonObservation]:
    """Extract person observations from one Ultralytics YOLO/ByteTrack result.

    When the result carries a `keypoints` attribute (pose models like
    yolo11n-pose.pt), each observation also includes a normalised keypoint
    dict {kpt_idx: (x_norm, y_norm, conf)}. `frame_size` (width, height)
    is required to normalise keypoint coords; if not provided keypoints
    are skipped silently and detector falls back to bbox-only behaviour.
    """

    boxes = getattr(result, "boxes", None)
    if boxes is None:
        return []

    xyxy = _to_numpy(getattr(boxes, "xyxy", None))
    if xyxy is None or xyxy.size == 0:
        return []

    conf = _to_numpy(getattr(boxes, "conf", None))
    cls = _to_numpy(getattr(boxes, "cls", None))
    ids = _to_numpy(getattr(boxes, "id", None))

    # Pose models attach keypoints as result.keypoints.xy (n, 17, 2) and
    # result.keypoints.conf (n, 17). Bbox models return None for this.
    kpts_xy = None
    kpts_conf = None
    kp_attr = getattr(result, "keypoints", None)
    if kp_attr is not None and frame_size is not None:
        kpts_xy = _to_numpy(getattr(kp_attr, "xy", None))
        kpts_conf = _to_numpy(getattr(kp_attr, "conf", None))

    observations: list[PersonObservation] = []

    for i, raw_bbox in enumerate(np.asarray(xyxy).reshape((-1, 4))):
        confidence = 1.0 if conf is None or len(conf) <= i else float(conf[i])
        class_id = 0 if cls is None or len(cls) <= i else int(cls[i])
        if class_id != 0 or confidence < min_confidence:
            continue
        # 6/4 r22: reject whole-frame bboxes. When no person is in the
        # room the model occasionally hallucinates a "person" that
        # covers the entire frame — bbox area >= 0.85 of total. Real
        # persons in a top-down install fill at most ~30% of the frame.
        # A bbox >0.7 is always a hallucination. Drop it before it
        # poisons the scene aggregates and triggers phantom CV7 events.
        if frame_size is not None:
            fw, fh = frame_size
            fw = max(1, int(fw))
            fh = max(1, int(fh))
            x1, y1, x2, y2 = (float(v) for v in raw_bbox)
            bbox_area_norm = (abs(x2 - x1) * abs(y2 - y1)) / (fw * fh)
            if bbox_area_norm >= 0.70:
                continue
        if ids is None or len(ids) <= i or np.isnan(float(ids[i])):
            track_id = None
        else:
            track_id = int(ids[i])
        bbox = tuple(round(float(v), 3) for v in raw_bbox)

        keypoints = None
        if kpts_xy is not None and kpts_conf is not None and i < len(kpts_xy) and frame_size is not None:
            fw, fh = frame_size
            fw = max(1, int(fw))
            fh = max(1, int(fh))
            kpts: dict[int, tuple[float, float, float]] = {}
            person_xy = np.asarray(kpts_xy[i])
            person_conf = np.asarray(kpts_conf[i])
            for kpt_idx in range(min(len(person_xy), len(person_conf))):
                x, y = person_xy[kpt_idx]
                c = float(person_conf[kpt_idx])
                # 0,0 is the placeholder ultralytics uses for missing
                # keypoints. Skip those plus anything below confidence.
                if c <= 0.0 or (x == 0.0 and y == 0.0):
                    continue
                kpts[int(kpt_idx)] = (
                    float(x) / fw,
                    float(y) / fh,
                    round(c, 4),
                )
            if kpts:
                keypoints = kpts

        observations.append(
            PersonObservation(
                track_id=track_id,
                bbox_xyxy=bbox,
                confidence=round(confidence, 6),
                keypoints=keypoints,
            )
        )
    return observations


# 6/4 r18: COCO-17 skeleton edges. Each tuple is a pair of keypoint
# indices that form a bone. Ordered to draw torso/limb outline cleanly.
_COCO_SKELETON_EDGES: tuple[tuple[int, int], ...] = (
    (5, 7), (7, 9),       # left shoulder → elbow → wrist
    (6, 8), (8, 10),      # right shoulder → elbow → wrist
    (11, 13), (13, 15),   # left hip → knee → ankle
    (12, 14), (14, 16),   # right hip → knee → ankle
    (5, 6), (11, 12),     # shoulder line, hip line
    (5, 11), (6, 12),     # torso sides
    (0, 5), (0, 6),       # head to shoulders
)

# Subset of keypoints we highlight as solid dots in the overlay — the
# ones the pose movement source actually consults. Everything else gets
# drawn as a small ring so the operator can still see the skeleton.
# 6/4 r19: includes elbows now (matches _GESTURE_KEYPOINTS).
_HIGHLIGHTED_KEYPOINTS = {0, 7, 8, 9, 10, 15, 16}  # nose, L/R elbow, L/R wrist, L/R ankle


def _draw_skeleton(
    draw: ImageDraw.ImageDraw,
    keypoints: dict[int, tuple[float, float, float]],
    width: int,
    height: int,
    color: tuple[int, int, int],
    line_w: int,
) -> None:
    """Draw a COCO-17 skeleton overlay for a single track.

    Keypoints below _KEYPOINT_MIN_CONFIDENCE are skipped. Gesture
    keypoints (the same set the pose movement source watches) render
    as filled circles; the rest render as outlined rings so the
    operator can read at a glance which limbs are driving CV7.
    """
    # Pixel coords for confident keypoints only.
    pixels: dict[int, tuple[int, int]] = {}
    for kpt_idx, (x_norm, y_norm, conf) in keypoints.items():
        if conf < _KEYPOINT_MIN_CONFIDENCE:
            continue
        px = int(round(x_norm * width))
        py = int(round(y_norm * height))
        if 0 <= px < width and 0 <= py < height:
            pixels[kpt_idx] = (px, py)
    # Bones
    bone_width = max(1, line_w - 1)
    for a, b in _COCO_SKELETON_EDGES:
        if a in pixels and b in pixels:
            draw.line((pixels[a], pixels[b]), fill=color, width=bone_width)
    # Keypoint markers
    # 6/4 r19: highlighted keypoint dots used to be barely visible (~5px
    # on a 720p frame). Bumped 70% so wrist/elbow markers POP on the
    # preview — operator should be able to spot a hand wave at a glance.
    dot_r = max(4, int(round((line_w + 1) * 1.7)))
    ring_r = max(2, line_w)
    for kpt_idx, (px, py) in pixels.items():
        if kpt_idx in _HIGHLIGHTED_KEYPOINTS:
            draw.ellipse((px - dot_r, py - dot_r, px + dot_r, py + dot_r), fill=color)
        else:
            draw.ellipse((px - ring_r, py - ring_r, px + ring_r, py + ring_r), outline=color, width=1)


def annotate_person_scene(
    image: Image.Image,
    scene: PersonScene,
    *,
    chord_label: str | None = None,
    track_ages: dict[int, int] | None = None,
) -> Image.Image:
    """Return an RGB preview image with tracked people and scene features overlaid.

    `chord_label` is rendered into the top status bar when present.
    `track_ages` maps track id -> frame count, drawn next to the bbox label.
    """

    annotated = image.convert("RGB").copy()
    draw = ImageDraw.Draw(annotated)
    width, height = annotated.size
    line_w = max(2, int(round(min(width, height) / 180)))
    colors = [(68, 255, 154), (64, 186, 255), (255, 214, 90), (255, 112, 195), (190, 142, 255)]

    for idx, track in enumerate(scene.tracks):
        color = colors[idx % len(colors)]
        x1, y1, x2, y2 = [int(round(v)) for v in track.bbox_xyxy]
        draw.rectangle((x1, y1, x2, y2), outline=color, width=line_w)
        age_str = ""
        if track_ages is not None and track.id in track_ages:
            age_str = f" a{track_ages[track.id]}"
        # 6/4 r19: overlay shows stable_id (persistent across ByteTrack
        # id churn) — humans can follow "P3" across hundreds of frames
        # without the label flickering. ByteTrack's raw id still drives
        # internal memory keys; this is purely cosmetic but makes the
        # preview infinitely more readable.
        display_id = f"P{track.stable_id}" if track.stable_id else f"id {track.id}"
        label = f"{display_id}{age_str} {track.confidence:.2f} d{track.distance:.2f} v{track.movement:.2f}"
        text_box = draw.textbbox((x1, max(0, y1 - 14)), label)
        draw.rectangle(text_box, fill=(0, 0, 0))
        draw.text((x1, max(0, y1 - 14)), label, fill=color)
        cx = int(round(track.center_x * width))
        cy = int(round(track.center_y * height))
        draw.ellipse((cx - 3, cy - 3, cx + 3, cy + 3), outline=color, width=line_w)
        # 6/4 r18: skeleton overlay when pose keypoints present. We draw
        # confident gesture keypoints (wrists, ankles, head) plus a thin
        # link line between them and the bbox centroid so the operator
        # can see at a glance which limbs are driving CV7. Skip rendering
        # entirely when the detector is bbox-only (track.keypoints is None).
        if track.keypoints:
            _draw_skeleton(draw, track.keypoints, width, height, color, line_w)

    # 6/6: removed the top-left "people N activity X near X spread X chord …"
    # summary bar — Pablo wants the camera image clean. Track bboxes, stable
    # IDs and the centroid crosshair stay because those are spatial info
    # operators read off the frame; the summary text is available out-of-band
    # in /status.json on the scene server.
    centroid = (int(round(scene.centroid_x * width)), int(round(scene.centroid_y * height)))
    draw.line((centroid[0] - 9, centroid[1], centroid[0] + 9, centroid[1]), fill=(255, 255, 255), width=line_w)
    draw.line((centroid[0], centroid[1] - 9, centroid[0], centroid[1] + 9), fill=(255, 255, 255), width=line_w)
    return annotated


class SceneServer:
    """Tiny HTTP server that exposes the annotated scene preview JPG + status.

    Routes:
      GET /             — minimal HTML viewer (annotated frame + live tail)
      GET /scene.jpg    — current preview frame (always latest atomic-written)
      GET /status.json  — full SWN bridge status JSON (cv values, chord, scene)
      GET /room_audio.json — room audio probe status (rms, peak, bands, dom_freq)

    Runs in a daemon thread so the bridge main loop owns lifecycle. Designed
    to live behind Tailscale serve (path-scoped HTTPS) — no auth here.
    The server reads the configured files from disk on each request so the
    main loop's atomic-write pattern remains the single source of truth.
    """

    def __init__(
        self,
        port: int,
        preview_path: Path,
        host: str = "127.0.0.1",
        status_path: Path | None = None,
        room_audio_path: Path | None = None,
    ) -> None:
        from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

        self.port = int(port)
        self.host = host
        self.preview_path = Path(preview_path)
        self.status_path = Path(status_path) if status_path else None
        self.room_audio_path = Path(room_audio_path) if room_audio_path else None
        preview_ref = self.preview_path
        status_ref = self.status_path
        room_ref = self.room_audio_path

        HTML_PAGE = (
            "<!doctype html>\n"
            "<html><head><meta charset=\"utf-8\"><base href=\"./\"><title>lisbon scene</title>\n"
            "<style>\n"
            "  html,body{margin:0;background:#0a0a0a;color:#ddd;font-family:ui-monospace,monospace}\n"
            "  #img{position:fixed;inset:0;background:#000}\n"
            "  #img img{width:100%;height:100%;object-fit:contain;display:block}\n"
            "  #panel{position:fixed;right:8px;top:8px;bottom:8px;width:380px;background:rgba(0,0,0,.40);border:1px solid #333;padding:12px;font-size:11px;overflow-y:auto;line-height:1.55}\n"
            "  .lbl{color:#777;display:inline-block;width:88px}\n"
            "  .bar{display:inline-block;background:#222;width:130px;height:8px;vertical-align:middle;margin-left:4px}\n"
            "  .bar > i{display:block;height:100%;background:#c0392b}\n"
            "  .sec{margin-top:10px;border-top:1px solid #2a2a2a;padding-top:8px;color:#888}\n"
            "  h1{font-size:11px;margin:0 0 8px;color:#888;letter-spacing:.08em}\n"
            "  b{color:#eee}\n"
            "</style></head>\n"
            "<body><div id=\"img\"><img id=\"s\" src=\"scene.jpg\"></div>\n"
            "<div id=\"panel\"><h1>LISBON LIVE TAIL</h1><div id=\"out\">loading...</div></div>\n"
            "<script>\n"
            "const f=n=>n==null?'-':(+n).toFixed(3);\n"
            "const bar=(v,max)=>{const p=Math.max(0,Math.min(1,(v||0)/(max||1)));return `<span class=bar><i style=width:${(p*100).toFixed(0)}%></i></span>`};\n"
            "function row(lbl,val,max,note){return `<div><span class=lbl>${lbl}</span><b>${f(val)}</b>${max?bar(val,max):''}${note?' <span style=color:#888>'+note+'</span>':''}</div>`}\n"
            "let im=document.getElementById('s');\n"
            "setInterval(()=>{ im.src='scene.jpg?t='+Date.now() }, 100);\n"
            "async function poll(){\n"
            "  try{\n"
            "    const [s,r]=await Promise.all([\n"
            "      fetch('status.json?t='+Date.now()).then(x=>x.json()),\n"
            "      fetch('room_audio.json?t='+Date.now()).then(x=>x.ok?x.json():null).catch(()=>null)\n"
            "    ]);\n"
            "    const cv=s.cv||{}, ch=s.chord||{}, sc=s.person_scene||{}, mx=s.max_cv||0.18;\n"
            "    const vo=ch.voice_offsets||[];\n"
            "    let h=`<div class=sec>CHORD</div>`;\n"
            "    h+=`<div><span class=lbl>voicing</span><b>${ch.voicing||'(none)'}</b></div>`;\n"
            "    h+=`<div><span class=lbl>root semi</span><b>${f(ch.root_semitones)}</b></div>`;\n"
            "    h+=`<div><span class=lbl>voices</span><b>${vo.map(f).join(' / ')}</b></div>`;\n"
            "    h+=`<div class=sec>CV (max=${mx})</div>`;\n"
            "    h+=row('cv1 voice1',cv.cv1_voice1_1v_oct,mx);\n"
            "    h+=row('cv2 voice2',cv.cv2_voice2_1v_oct,mx);\n"
            "    h+=row('cv3 voice3',cv.cv3_voice3_1v_oct,mx);\n"
            "    h+=row('cv4 browse',cv.cv4_wavetable_browse,mx);\n"
            "    h+=row('cv5 transpose',cv.cv5_transpose,mx);\n"
            "    h+=row('cv6 MIX VCA',cv.cv6_main_mix_vca,mx,'Quad VCA');\n"
            "    h+=row('cv7 GLITCH',cv.cv7_glitch_trigger,mx,'O&C gate');\n"
            "    h+=row('cv8 depth',cv.cv8_depth,mx);\n"
            "    h+=`<div class=sec>SCENE</div>`;\n"
            "    h+=`<div><span class=lbl>people</span><b>${sc.people_count||0}</b></div>`;\n"
            "    h+=row('activity',sc.activity,1);\n"
            "    h+=row('movement',sc.movement,1);\n"
            "    h+=row('nearest',sc.nearest_distance,1);\n"
            "    h+=row('spread',sc.spread_x,1);\n"
            "    h+=`<div><span class=lbl>frames</span><b>${s.frames_seen}</b></div>`;\n"
            "    if(r){\n"
            "      h+=`<div class=sec>MIC (${r.device||''})</div>`;\n"
            "      h+=row('rms',r.rms,0.3);\n"
            "      h+=row('peak',r.peak,0.5);\n"
            "      h+=`<div><span class=lbl>dom freq</span><b>${(r.dom_freq_hz||0).toFixed(0)} Hz</b></div>`;\n"
            "      h+=row('low band',r.band_low,1);\n"
            "      h+=row('mid band',r.band_mid,1);\n"
            "      h+=row('high band',r.band_high,1);\n"
            "      const age=Math.max(0,(Date.now()/1000)-(r.timestamp||0));\n"
            "      h+=`<div><span class=lbl>age</span><b>${age.toFixed(1)}s</b></div>`;\n"
            "    }else{ h+=`<div class=sec>MIC</div><div style=color:#a33>probe silent</div>`; }\n"
            "    document.getElementById('out').innerHTML=h;\n"
            "  }catch(e){ document.getElementById('out').innerHTML='err: '+e.message; }\n"
            "}\n"
            "poll(); setInterval(poll,300);\n"
            "</script>\n"
            "</body></html>"
        ).encode("utf-8")

        def _serve_file(handler, path: Path | None, content_type: str) -> None:
            if path is None:
                handler.send_response(404); handler.end_headers(); return
            try:
                data = path.read_bytes()
            except (FileNotFoundError, OSError):
                handler.send_response(503); handler.end_headers(); return
            handler.send_response(200)
            handler.send_header("Content-Type", content_type)
            handler.send_header("Cache-Control", "no-store")
            handler.send_header("Access-Control-Allow-Origin", "*")
            handler.send_header("Content-Length", str(len(data)))
            handler.end_headers()
            handler.wfile.write(data)

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, fmt, *args):
                return

            def do_GET(self):  # noqa: N802
                if self.path == "/" or self.path.startswith("/?"):
                    self.send_response(200)
                    self.send_header("Content-Type", "text/html; charset=utf-8")
                    self.send_header("Cache-Control", "no-store")
                    self.send_header("Content-Length", str(len(HTML_PAGE)))
                    self.end_headers()
                    self.wfile.write(HTML_PAGE)
                    return
                if self.path.startswith("/scene.jpg"):
                    _serve_file(self, preview_ref, "image/jpeg")
                    return
                if self.path.startswith("/status.json"):
                    _serve_file(self, status_ref, "application/json; charset=utf-8")
                    return
                if self.path.startswith("/room_audio.json"):
                    _serve_file(self, room_ref, "application/json; charset=utf-8")
                    return
                self.send_response(404)
                self.end_headers()

        self._server = ThreadingHTTPServer((host, self.port), Handler)
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True, name="lisbon-scene-server")

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        try:
            self._server.shutdown()
            self._server.server_close()
        except Exception:
            pass


class YoloByteTrackPersonDetector:
    """Lazy Ultralytics YOLO + ByteTrack wrapper for person observations."""

    def __init__(self, model_name: str = "yolo11n.pt", *, confidence: float = 0.35, tracker: str = "bytetrack.yaml", imgsz: int = 480) -> None:
        from ultralytics import YOLO

        self.model = YOLO(model_name)
        self.confidence = float(confidence)
        self.tracker = tracker
        self.imgsz = int(imgsz)

    def detect(self, image: Image.Image) -> list[PersonObservation]:
        frame = np.asarray(image.convert("RGB"))
        results = self.model.track(
            frame,
            persist=True,
            classes=[0],
            conf=self.confidence,
            tracker=self.tracker,
            imgsz=self.imgsz,
            verbose=False,
        )
        if not results:
            return []
        return observations_from_yolo_result(
            results[0],
            min_confidence=self.confidence,
            frame_size=image.size,
        )


@dataclass(frozen=True)
class BridgeStatus:
    ok: bool
    timestamp: float
    device: str
    sample_rate: int
    blocksize: int
    main_gain: float
    max_cv: float
    vision_mode: str
    features: CameraFeatures
    cv: dict[str, float]
    coreaudio_outputs: dict[str, int]
    frames_seen: int
    person_scene: PersonScene | None = None
    audio_input: dict[str, Any] | None = None
    preview_path: str | None = None
    error: str | None = None


class CameraFeatureTracker:
    """Tiny frame differencer for room-scale modulation.

    It deliberately avoids OpenCV/YOLO for the first hardware jam: we only need
    aggregate motion and broad spatial mass to prove camera → CV control.
    """

    def __init__(self, sample_size: tuple[int, int] = (96, 54)) -> None:
        self.sample_size = sample_size
        self._previous_gray: np.ndarray | None = None

    def update(self, image: Image.Image) -> CameraFeatures:
        gray = image.convert("L").resize(self.sample_size, Image.Resampling.BILINEAR)
        arr = np.asarray(gray, dtype=np.float32) / 255.0

        brightness = float(np.mean(arr))
        if self._previous_gray is None:
            motion = 0.0
        else:
            motion = float(np.mean(np.abs(arr - self._previous_gray)))
        self._previous_gray = arr

        total = float(np.sum(arr))
        if total <= 1e-6:
            centroid_x = 0.5
            centroid_y = 0.5
        else:
            h, w = arr.shape
            xs = np.linspace(0.0, 1.0, w, dtype=np.float32)
            ys = np.linspace(0.0, 1.0, h, dtype=np.float32)
            centroid_x = float(np.sum(arr * xs[None, :]) / total)
            centroid_y = float(np.sum(arr * ys[:, None]) / total)

        return CameraFeatures(
            brightness=_clamp01(brightness),
            motion=_clamp01(motion),
            centroid_x=_clamp01(centroid_x),
            centroid_y=_clamp01(centroid_y),
        )


class LisbonSwnMapper:
    """Map camera features to the current SWN patch's eight ES-9 CV outs."""

    def __init__(self, max_cv: float = 0.25, smoothing_hz: float = 8.0) -> None:
        if max_cv <= 0.0 or max_cv > 1.0:
            raise ValueError("max_cv should be in normalized ES-9 units, usually 0.05..0.30")
        self.max_cv = float(max_cv)
        self.smoothing_hz = float(smoothing_hz)
        self._current: list[float] | None = None
        # Chord layer — voices 1/2/3 V/oct positions, in semitone offsets
        # from the root. The bridge's main loop pushes a resolved chord here
        # from the live heuristic profile. None = use hardcoded open_fifth.
        self._chord: dict | None = None
        self._chord_previous: dict | None = None
        self._chord_set_at: float = 0.0
        self._chord_now = time.monotonic
        # Glacial drift baseline — captured once at mapper construction so
        # the autonomous LFO phase is stable across the process lifetime.
        # Restarting the bridge re-seeds the drift, which is desired (each
        # show starts at zero drift, gathers over the session).
        self._drift_start: float = self._chord_now()

    def set_chord(self, chord: dict | None) -> None:
        """Receive a chord block resolved by audio.chord_palette.resolve_chord.

        If the new chord differs from the current one (or current is None),
        snapshot the existing chord and start a transition timer so the
        bridge crossfades over chord.transition_seconds.
        """
        if chord is None:
            self._chord = None
            self._chord_previous = None
            return
        if self._chord is None or chord.get("voice_offsets") != self._chord.get("voice_offsets") or \
                chord.get("root_semitones") != self._chord.get("root_semitones"):
            self._chord_previous = self._chord
            self._chord_set_at = self._chord_now()
        self._chord = chord

    def _active_chord(self) -> dict | None:
        """Return the currently-playing chord, blended if a transition is in flight."""
        if self._chord is None:
            return None
        elapsed = self._chord_now() - self._chord_set_at
        blended = interpolate_chord(self._chord_previous, self._chord, elapsed_seconds=elapsed)
        # Glacial autonomous drift — runs even when no reviewer profile arrives.
        # Phase is the monotonic clock since mapper construction, so different
        # mapper instances have independent drift trajectories (each install
        # starts at its own phase) and the drift is continuous across chord
        # changes (the LFO doesn't reset when the reviewer picks a new chord).
        drift_phase = self._chord_now() - self._drift_start
        return apply_chord_drift(blended, drift_phase_seconds=drift_phase)

    def step(
        self,
        *,
        brightness: float,
        motion: float,
        centroid_x: float,
        centroid_y: float,
        dt: float,
    ) -> list[float]:
        brightness = _clamp01(brightness)
        motion = _clamp01(motion)
        centroid_x = _clamp01(centroid_x)
        centroid_y = _clamp01(centroid_y)
        dt = max(0.0, float(dt))

        activity = _clamp01((motion * 0.75) + (brightness * 0.25))

        # ES-9 normalized convention in the Lisbon docs: 1.0 ~= +10 V.
        # For 1V/oct, one semitone ~= 0.008333. Keep the camera-induced pitch
        # wobble intentionally tiny; CV1-3 are musical roots, not wild mod busses.
        semitone = 1.0 / 120.0
        # Chord layer: when the reflective reviewer has set a chord, use its
        # root + voice offsets. Otherwise fall back to the historical
        # [0, 7, 12] open-fifth so existing tests stay green.
        active_chord = self._active_chord()
        if active_chord is not None:
            root_semi = float(active_chord.get("root_semitones", 0.0)) - 36.0  # normalize to relative
            voice_offsets = active_chord.get("voice_offsets", (0.0, 7.0, 12.0))
            wander_scale = float(active_chord.get("pitch_wander_scale", 1.0))
        else:
            root_semi = 0.0
            voice_offsets = (0.0, 7.0, 12.0)
            wander_scale = 1.0
        pitch_wander = ((centroid_x - 0.5) * (0.9 * semitone) + motion * (0.5 * semitone)) * wander_scale

        # CV6 -> Intellijel Quad VCA CV1 (normalled to VCA2/3/4). Single CV
        # controls both main mix channels. In aggregate (no-people) mode we
        # ride brightness + activity for a slow swell.
        # Live test 2026-06-03: original 0.60..0.90 swing was too narrow to
        # hear with VCA on exponential or LEVEL pot biased open. Widening
        # to 0.10..0.95 so the modulation is unambiguous on the rig — quiet
        # room should be perceptibly quieter than busy room.
        mix_target = 0.00 + 1.00 * _clamp01(0.55 * brightness + 0.45 * activity)
        targets = [
            (root_semi + voice_offsets[0]) * semitone + pitch_wander,
            (root_semi + voice_offsets[1]) * semitone + pitch_wander,
            (root_semi + voice_offsets[2]) * semitone + pitch_wander,
            0.025 + 0.165 * ((centroid_x * 0.65) + (activity * 0.35)),  # browse
            self.max_cv * (0.50 + 0.35 * (0.5 - centroid_y)),  # cv5 transpose (was dispersion 6/3)
            self.max_cv * mix_target,  # CV6 main mix VCA
            0.0 if motion < 0.03 else self.max_cv,  # CV7 glitch trigger (6/4 r8: sensitivity bump 0.06→0.04)
            0.035 + 0.190 * activity,  # depth
        ]
        return _slew_targets(targets, current_attr="_current", owner=self, max_cv=self.max_cv, smoothing_hz=self.smoothing_hz, dt=dt, per_channel_smoothing_hz=PER_CV_SMOOTHING_HZ)


class HumanAwareSwnMapper:
    """Map stable human scene features to the current SWN patch's eight CV outs.

    This is deliberately more graded than the first global brightness/motion mapper:
    person count, approximate distance, spread, and movement all contribute to
    timbral controls while pitch stays in a narrow musical band. CV7 is reserved
    for the O&C glitch-gate patch: it is a smoothed room-movement CV, not a
    presence/spread control, so a still room keeps the gate low.
    """

    def __init__(self, max_cv: float = 0.25, smoothing_hz: float = 8.0) -> None:
        if max_cv <= 0.0 or max_cv > 1.0:
            raise ValueError("max_cv should be in normalized ES-9 units, usually 0.05..0.30")
        self.max_cv = float(max_cv)
        self.smoothing_hz = float(smoothing_hz)
        # Input-side smoothing on presence (0..1) to absorb YOLO detection
        # dropouts. Without this, mean_distance toggles 0.60 <-> 0.00 several
        # times per second when YOLO loses+reacquires a track. Slewing the
        # *output* CV can't fix that — by the time CV6 reaches one value
        # the input has snapped to the other. We low-pass the presence
        # input itself before it touches CV.
        # Live tuning 6/3 round 9: 0.6Hz (~265ms tau) preserves walk
        # responsiveness while making 1-2 frame detection gaps invisible.
        self._presence_state: float = 0.0
        self._presence_smoothing_hz: float = 0.6
        self._current: list[float] | None = None
        # CV4 (BROWSE) autonomous LFO state. Operator 6/4 r5: CV4 should be
        # an always-on evolving signal that walks through the wavetable
        # continuously, with rate modulated by presence. Empty room ->
        # glacial drift (~0.04 Hz, full traversal ~25s). Full active room
        # -> faster wander (~0.5 Hz, full traversal ~2s). Never stops.
        # The walk is a phase-accumulating triangle so it's smooth and
        # has no abrupt jumps; combined with the scene-driven rate this
        # gives a wavetable position that never settles.
        self._browse_phase: float = 0.0  # 0..1, accumulates with time*rate
        # 6/4 r13: hot-tunable knobs read from heuristic_profile.json's
        # `tune` block. Default values match the previous source-hardcoded
        # versions so behavior is unchanged until the profile writes new
        # values. The set_tuning() method updates them atomically.
        self.glitch_fire_threshold: float = 0.03
        self.browse_rate_min_hz: float = 0.018
        self.browse_rate_max_hz: float = 0.100
        # 6/4 r14: CV7 latch with decay. Pure binary fire was technically
        # correct but read as "unreliable" because YOLO emits movement
        # signals on isolated frames (5Hz camera, movement computed only
        # on the frame where bbox center jumps). Latching holds CV7 at
        # max_cv for hold_ms after a trigger, then exp-decays over
        # release_ms so subsequent gaps between detection frames don't
        # collapse the strobe. Hot-tunable via cv7_hold_ms / cv7_release_ms.
        self.cv7_hold_ms: float = 250.0     # full max_cv for this long after trigger
        self.cv7_release_ms: float = 350.0  # then exp-decay to 0 with this tau
        self._cv7_latch_elapsed_ms: float | None = None  # None = idle, else ms since trigger
        # Chord layer — voices 1/2/3 V/oct positions, semitone offsets from
        # root. None = use the historical hardcoded open-fifth.
        self._chord: dict | None = None
        self._chord_previous: dict | None = None
        self._chord_set_at: float = 0.0
        self._chord_now = time.monotonic
        # Glacial drift baseline — captured once at mapper construction so
        # the autonomous LFO phase is stable across the process lifetime.
        # Restarting the bridge re-seeds the drift, which is desired (each
        # show starts at zero drift, gathers over the session).
        self._drift_start: float = self._chord_now()

    def set_tuning(self, *, glitch_fire_threshold: float | None = None, browse_rate_min_hz: float | None = None, browse_rate_max_hz: float | None = None, cv7_hold_ms: float | None = None, cv7_release_ms: float | None = None) -> None:
        """Hot-update HumanAwareSwnMapper tuning knobs from the profile poller."""
        if glitch_fire_threshold is not None:
            new_val = max(0.0, float(glitch_fire_threshold))
            if abs(new_val - self.glitch_fire_threshold) > 1e-6:
                print(f"[poll-tune] glitch_fire_threshold {self.glitch_fire_threshold:.4f} -> {new_val:.4f}", flush=True)
                self.glitch_fire_threshold = new_val
        if browse_rate_min_hz is not None:
            new_val = max(0.0, float(browse_rate_min_hz))
            if abs(new_val - self.browse_rate_min_hz) > 1e-6:
                print(f"[poll-tune] browse_rate_min_hz {self.browse_rate_min_hz:.4f} -> {new_val:.4f}", flush=True)
                self.browse_rate_min_hz = new_val
        if browse_rate_max_hz is not None:
            new_val = max(0.0, float(browse_rate_max_hz))
            if abs(new_val - self.browse_rate_max_hz) > 1e-6:
                print(f"[poll-tune] browse_rate_max_hz {self.browse_rate_max_hz:.4f} -> {new_val:.4f}", flush=True)
                self.browse_rate_max_hz = new_val
        if cv7_hold_ms is not None:
            new_val = max(0.0, float(cv7_hold_ms))
            if abs(new_val - self.cv7_hold_ms) > 1e-3:
                print(f"[poll-tune] cv7_hold_ms {self.cv7_hold_ms:.1f} -> {new_val:.1f}", flush=True)
                self.cv7_hold_ms = new_val
        if cv7_release_ms is not None:
            new_val = max(1.0, float(cv7_release_ms))
            if abs(new_val - self.cv7_release_ms) > 1e-3:
                print(f"[poll-tune] cv7_release_ms {self.cv7_release_ms:.1f} -> {new_val:.1f}", flush=True)
                self.cv7_release_ms = new_val

    def set_chord(self, chord: dict | None) -> None:
        """Receive a chord block resolved by audio.chord_palette.resolve_chord.

        Detects whether the new chord differs from the current one and, if
        so, snapshots the prior chord and starts a transition timer so the
        bridge crossfades over `chord.transition_seconds`.
        """
        if chord is None:
            self._chord = None
            self._chord_previous = None
            return
        if self._chord is None or chord.get("voice_offsets") != self._chord.get("voice_offsets") or \
                chord.get("root_semitones") != self._chord.get("root_semitones"):
            self._chord_previous = self._chord
            self._chord_set_at = self._chord_now()
        self._chord = chord

    def _active_chord(self) -> dict | None:
        if self._chord is None:
            return None
        elapsed = self._chord_now() - self._chord_set_at
        blended = interpolate_chord(self._chord_previous, self._chord, elapsed_seconds=elapsed)
        # Glacial autonomous drift — runs even when no reviewer profile arrives.
        # Phase is the monotonic clock since mapper construction, so different
        # mapper instances have independent drift trajectories (each install
        # starts at its own phase) and the drift is continuous across chord
        # changes (the LFO doesn't reset when the reviewer picks a new chord).
        drift_phase = self._chord_now() - self._drift_start
        return apply_chord_drift(blended, drift_phase_seconds=drift_phase)

    def _filter_presence(self, raw_presence: float, dt: float) -> float:
        """One-pole low-pass on raw presence to absorb YOLO detection
        dropouts before they reach CV6. The CV-side slew is separate and
        handles short-timescale jitter; this filter handles the longer
        2-3 frame detection gaps.
        """
        raw = float(np.clip(raw_presence, 0.0, 1.0))
        if dt <= 0.0:
            alpha = 1.0
        else:
            alpha = 1.0 - math.exp(-self._presence_smoothing_hz * dt)
        alpha = float(np.clip(alpha, 0.0, 1.0))
        self._presence_state = self._presence_state + (raw - self._presence_state) * alpha
        return float(np.clip(self._presence_state, 0.0, 1.0))

    def _movement_gate_target(self, scene: PersonScene, dt: float = 0.0) -> float:
        """CV7 glitch trigger — latching binary fire with exp decay.

        Pre-r14 was pure binary fire (snap to max_cv if movement crossed
        threshold, else 0). Technically correct but read as unreliable
        because YOLO's per-frame movement signal is sparse: at 5Hz camera
        with movement computed only on the frame where bbox center jumps,
        most frames show movement=0 even while the person is actually
        moving. CV7 then snapped 0 → max → 0 between detection frames =
        sub-frame strobe ticks that the downstream consumers (O&C gate,
        ESP32 strobe sync) couldn't reliably catch.

        Now: when movement crosses threshold, latch CV7 at max_cv and
        track elapsed time via accumulated dt (same clock source as the
        rest of the mapper, deterministic in tests). Inside the hold
        window output stays at max_cv. After hold, exp-decays to 0 over
        release_ms. Any new trigger inside either window re-arms (full
        max_cv, hold timer reset). Once decayed output drops below 5%
        of max_cv, latch clears.
        """
        movement = max(_clamp01(scene.movement), _clamp01(scene.activity))
        # Re-arm on any qualifying motion (reset elapsed to 0).
        if movement >= self.glitch_fire_threshold:
            self._cv7_latch_elapsed_ms = 0.0
            return float(self.max_cv)
        # Idle when no latch active.
        if self._cv7_latch_elapsed_ms is None:
            return 0.0
        # Accumulate elapsed time using the mapper's own dt clock.
        self._cv7_latch_elapsed_ms += max(0.0, dt) * 1000.0
        elapsed_ms = self._cv7_latch_elapsed_ms
        hold_ms = self.cv7_hold_ms
        release_ms = max(1.0, self.cv7_release_ms)
        if elapsed_ms < hold_ms:
            return float(self.max_cv)
        release_elapsed = elapsed_ms - hold_ms
        envelope = math.exp(-release_elapsed / release_ms)
        if envelope < 0.05:
            self._cv7_latch_elapsed_ms = None
            return 0.0
        return float(self.max_cv * envelope)

    def _browse_target(self, scene: PersonScene, dt: float) -> float:
        """CV4 (BROWSE) — always-on evolving wavetable position.

        Operator 6/4 r5: CV4 should be a continuously walking signal whose
        rate scales with presence, never settling. Empty room walks slowly
        (~25s full traversal), full active room walks fast (~2s traversal).

        Implementation: phase accumulator advancing every step by `rate*dt`,
        wrapped 0..1, mapped through a triangle wave so the output reverses
        smoothly at the ends instead of jumping. Output scaled to the
        usable CV range 0.025..0.21 (same band as before so SWN's BROWSE
        knob doesn't need a new bias).
        """
        # Density of room presence drives the rate. count_norm + activity
        # so a still crowd already pushes rate up, plus movement pushes it
        # further. Empty room sits at min_rate.
        count = _clamp01(scene.count_norm)
        activity = _clamp01(scene.activity)
        movement = _clamp01(scene.movement)
        # Hz range hot-tunable via profile `tune` block. Default ~0.018..0.10
        # (55s..10s traversal); rate scales with presence within the band.
        rate_hz = self.browse_rate_min_hz + (self.browse_rate_max_hz - self.browse_rate_min_hz) * _clamp01(0.55 * count + 0.30 * activity + 0.15 * movement)
        self._browse_phase = (self._browse_phase + rate_hz * max(0.0, dt)) % 1.0
        # Triangle wave: 0..1..0 over phase 0..1
        if self._browse_phase < 0.5:
            tri = self._browse_phase * 2.0
        else:
            tri = 2.0 - self._browse_phase * 2.0
        # Map to CV band 0.025..0.21 (same as the pre-6/4 cv4 output range)
        return 0.025 + 0.185 * tri

    def _dispersion_target(self, scene: PersonScene) -> float:
        """CV8 (DISPERSION) — driven by audience physical spread.

        Operator 6/4 r5: CV4 is now the wavetable browser, CV8 patches
        into SWN DISPERSION. Musically: dispersion = textural fragmentation
        / grain spread, so it should respond to how PHYSICALLY DISPERSED
        the audience is, not how close any single person is.

        Inputs:
          spread_x (primary, 0.65 weight) — bbox spread across the frame
          count_norm (secondary, 0.25)     — more bodies = more spread material
          activity  (tertiary, 0.10)       — moving crowd adds shimmer

        Empty / single still person → CV8 ~ 0.025 (no dispersion, focused).
        Multiple bodies edge-to-edge → CV8 ~ 0.21 (full dispersion grain).
        """
        spread = _clamp01(scene.spread_x)
        count = _clamp01(scene.count_norm)
        activity = _clamp01(scene.activity)
        dispersion_signal = _clamp01(0.65 * spread + 0.25 * count + 0.10 * activity)
        return 0.025 + 0.185 * dispersion_signal

    def step_movement_gate_only(self, scene: PersonScene, current_values: Sequence[float], *, dt: float) -> list[float]:
        """Update CV7 (glitch) AND CV6 (mix VCA) during still-frame holds.

        Original design (early Lisbon): freeze all SWN voice CVs to avoid
        detector jitter, only let CV7 decay back to zero when the room
        settles. But CV6 (mix VCA) was added later and is bound to
        presence/distance, not motion — a person walking up to a frozen
        camera scene should still increase the mix volume. Live test 6/3:
        operator observed CV6 stuck at 0.018 for 12s because every frame
        was hitting this 'still' path.

        Solution: still update CV6 from the live scene during stillness
        holds. CV1-5 stay frozen (those are pitched/timbral). CV7 still
        gets the glitch-gate target (decays smoothly).
        """

        if len(current_values) != len(CV_LABELS):
            raise ValueError("expected 8 physical ES-9 CV values")
        if self._current is None or len(self._current) != len(CV_LABELS):
            self._current = [float(np.clip(v, 0.0, self.max_cv)) for v in current_values]
        targets = [float(np.clip(v, 0.0, self.max_cv)) for v in current_values]
        targets[MOVEMENT_GATE_CV_INDEX] = self._movement_gate_target(scene, dt=dt)
        # CV4 BROWSE — keep walking through stillness. The whole point of
        # the autonomous browse LFO is that it never stops; even a frozen
        # camera scene should keep evolving the wavetable position. dt
        # here is the actual elapsed time so the phase advances correctly
        # whether we're on the live or stillness path.
        targets[3] = self._browse_target(scene, dt)
        # CV6 main mix VCA — keep it responsive to presence during stillness,
        # same math as the live path in step_scene. Presence filtered through
        # the one-pole low-pass to absorb YOLO detection dropouts.
        mean_distance = _clamp01(scene.mean_distance)
        count = _clamp01(scene.count_norm)
        activity = _clamp01(scene.activity)
        raw_presence = 0.65 * mean_distance + 0.20 * count + 0.15 * activity
        presence = self._filter_presence(raw_presence, dt)
        mix_target = 0.00 + 1.00 * _clamp01(presence)
        targets[MAIN_MIX_VCA_CV_INDEX] = self.max_cv * mix_target
        return _slew_targets(targets, current_attr="_current", owner=self, max_cv=self.max_cv, smoothing_hz=self.smoothing_hz, dt=dt, per_channel_smoothing_hz=PER_CV_SMOOTHING_HZ)

    def step_scene(self, scene: PersonScene, *, dt: float) -> list[float]:
        dt = max(0.0, float(dt))
        semitone = 1.0 / 120.0
        x = _clamp01(scene.centroid_x)
        y = _clamp01(scene.centroid_y)
        spread = _clamp01(scene.spread_x)
        nearest = _clamp01(scene.nearest_distance)
        mean_distance = _clamp01(scene.mean_distance)
        movement = _clamp01(scene.movement)
        count = _clamp01(scene.count_norm)
        activity = _clamp01(scene.activity)

        # Tiny stable pitch signature: enough for identity/position shimmer, not
        # enough to turn the SWN into a random pitch machine.
        # Chord layer: when the reflective reviewer has set a chord, use its
        # root + voice offsets. Otherwise fall back to historical open-fifth
        # so existing tests stay green.
        active_chord = self._active_chord()
        if active_chord is not None:
            root_semi = float(active_chord.get("root_semitones", 36.0)) - 36.0
            voice_offsets = active_chord.get("voice_offsets", (0.0, 7.0, 12.0))
            wander_scale = float(active_chord.get("pitch_wander_scale", 1.0))
        else:
            root_semi = 0.0
            voice_offsets = (0.0, 7.0, 12.0)
            wander_scale = 1.0
        # Pitch wander — applied uniformly to all three voices, NOT per-voice
        # with different scales. The pre-6/4 design used per-voice scales
        # (1.0, 0.65, 0.42) which pushed voices apart by fractions of a
        # semitone, producing audible 1-2Hz beating between adjacent voices
        # (a 0.24 semitone gap at root D2 = 1Hz beat). Operator 6/4 r5
        # noted dissonance via mic check — beating between supposedly
        # unison voices on the 'grounding' voicing.
        #
        # Fix: compute a single global wander value, applied to all three
        # voices identically. The chord shape (voice_offsets from the
        # palette) stays exactly as the palette intends. Wander now moves
        # the WHOLE chord glacially around the root, not individual voices
        # against each other.
        pitch_wander = ((x - 0.5) * 0.85 + movement * 0.35 + count * 0.20) * semitone * wander_scale
        if scene.tracks:
            id_signature = sum(((track.id % 7) - 3) for track in scene.tracks[:3]) / 18.0
            pitch_wander += id_signature * semitone * wander_scale

        # CV6 -> Intellijel Quad VCA CV1 (normalled to VCA2/3/4). Controls
        # main mix L/R volume from a single CV. Live tuning 6/3 round 2:
        # operator reports cv6 frozen at one value despite walking around.
        # Root cause: previous presence math saturated the distance term
        # at mean_d < 0.3 so far-end movement had zero effect on the mix.
        # Rebuilt around mean_distance as the primary driver — distance IS
        # presence in a webcam install — with count and activity layered on
        # top as smaller modulations.
        #   distance dominant: closer person -> louder mix
        #   count secondary: more people -> slight boost
        #   activity tertiary: motion -> tiny swell
        # Live tuning 6/3: presence math + input-side low-pass filter to
        # absorb YOLO detection dropouts so CV6 doesn't whip 0..0.6..0
        # when a track is briefly lost.
        #   distance dominant: closer person -> louder mix
        #   count secondary: more people -> slight boost
        #   activity tertiary: motion swell
        raw_presence = (
            0.65 * mean_distance       # primary: closeness drives loudness
            + 0.20 * count             # secondary: more bodies, slight boost
            + 0.15 * activity          # tertiary: motion swell
        )
        presence = self._filter_presence(raw_presence, dt)
        mix_target = 0.00 + 1.00 * _clamp01(presence)
        targets = [
            (root_semi + voice_offsets[0]) * semitone + pitch_wander,
            (root_semi + voice_offsets[1]) * semitone + pitch_wander,
            (root_semi + voice_offsets[2]) * semitone + pitch_wander,
            self._browse_target(scene, dt),
            # CV5 -> SWN TRANSPOSE (was dispersion). Operator patched 6/3:
            # this is no longer textural drift, it's bipolar V/oct shift of
            # the whole oscillator bank. We give it a center-biased value
            # around max_cv/2 with a slow bipolar swing driven by centroid_y
            # (vertical position of bodies in the frame). People high in
            # frame -> transpose up; low -> down. The whole chord lifts or
            # weighs depending on where the room "points."
            # Sub-mHz LFO already lives at the chord layer (root drift), so
            # this signal is body-driven only — structural harmonic motion,
            # not gesture.
            self.max_cv * (0.50 + 0.35 * (0.5 - y)),  # cv5 transpose center+bipolar
            self.max_cv * mix_target,
            self._movement_gate_target(scene, dt=dt),
            self._dispersion_target(scene),
        ]
        return _slew_targets(targets, current_attr="_current", owner=self, max_cv=self.max_cv, smoothing_hz=self.smoothing_hz, dt=dt, per_channel_smoothing_hz=PER_CV_SMOOTHING_HZ)


def physical_cv_to_coreaudio_channel(physical_cv_output: int) -> int:
    """Return zero-based CoreAudio output channel for ES-9 physical CV out 1-8."""

    if not 1 <= physical_cv_output <= 8:
        raise ValueError("physical ES-9 CV output must be 1..8")
    return 8 + (physical_cv_output - 1)


def analyze_audio_block(indata: np.ndarray | None, *, sample_rate: int = 48_000, previous_peak: float = 0.0) -> dict[str, float]:
    """Return frequency/glitch features from selected ES-9 stereo input audio.

    Zero-crossing stays as a very cheap pitch-ish proxy, while a small per-block
    FFT gives enough band/centroid information to distinguish low drones from
    high-frequency glitch material for the light mapper.
    """

    empty = {
        "stereo_rms": 0.0,
        "stereo_peak": 0.0,
        "zero_crossing_hz": 0.0,
        "freq_hz": 0.0,
        "dominant_frequency_hz": 0.0,
        "spectral_centroid_hz": 0.0,
        "low_band_ratio": 0.0,
        "mid_band_ratio": 0.0,
        "high_band_ratio": 0.0,
        "high_freq_ratio": 0.0,
        "high_frequency_ratio": 0.0,
        "transient": 0.0,
        "transient_score": 0.0,
        "glitch_score": 0.0,
    }
    if indata is None or indata.ndim != 2 or indata.shape[0] < 2 or indata.shape[1] < 2:
        return empty

    stereo = np.asarray(indata[:, :2], dtype=np.float32)
    mix = np.mean(stereo, axis=1).astype(np.float64)
    rms = float(np.sqrt(np.mean(np.square(stereo))))
    peak = float(np.max(np.abs(stereo)))
    if rms <= 1e-7 and peak <= 1e-7:
        return empty

    signs = np.signbit(mix)
    crossings = int(np.count_nonzero(signs[1:] != signs[:-1]))
    zero_crossing_hz = (crossings * float(sample_rate)) / (2.0 * max(1, mix.size - 1))

    centered = mix - float(np.mean(mix))
    window = np.hanning(centered.size) if centered.size >= 8 else np.ones(centered.size)
    spectrum = np.fft.rfft(centered * window)
    freqs = np.fft.rfftfreq(centered.size, d=1.0 / float(sample_rate))
    power = np.square(np.abs(spectrum))
    if power.size:
        power[0] = 0.0
    total_power = float(np.sum(power))
    if total_power > 1e-18:
        dominant_idx = int(np.argmax(power))
        dominant_frequency_hz = float(freqs[dominant_idx])
        spectral_centroid_hz = float(np.sum(freqs * power) / total_power)
        low_band_ratio = float(np.sum(power[(freqs >= 20.0) & (freqs < 550.0)]) / total_power)
        mid_band_ratio = float(np.sum(power[(freqs >= 550.0) & (freqs < 1800.0)]) / total_power)
        high_band_ratio = float(np.sum(power[freqs >= 1800.0]) / total_power)
    else:
        dominant_frequency_hz = 0.0
        spectral_centroid_hz = 0.0
        low_band_ratio = 0.0
        mid_band_ratio = 0.0
        high_band_ratio = 0.0

    diff = np.diff(mix)
    diff_rms = float(np.sqrt(np.mean(np.square(diff)))) if diff.size else 0.0
    edge_ratio = _clamp01(diff_rms / max(rms, 1e-7))
    high_freq_ratio = _clamp01(max(edge_ratio, high_band_ratio))
    transient = _clamp01(max(0.0, peak - float(previous_peak)) / 0.35)
    glitch_score = _clamp01(max(0.58 * edge_ratio + 0.42 * transient, 0.48 * high_band_ratio + 0.52 * transient))

    freq_hz = dominant_frequency_hz if dominant_frequency_hz > 0 else zero_crossing_hz
    return {
        "stereo_rms": round(rms, 9),
        "stereo_peak": round(peak, 9),
        "zero_crossing_hz": round(float(zero_crossing_hz), 3),
        "freq_hz": round(float(freq_hz), 3),
        "dominant_frequency_hz": round(float(dominant_frequency_hz), 3),
        "spectral_centroid_hz": round(float(spectral_centroid_hz), 3),
        "low_band_ratio": round(float(_clamp01(low_band_ratio)), 9),
        "mid_band_ratio": round(float(_clamp01(mid_band_ratio)), 9),
        "high_band_ratio": round(float(_clamp01(high_band_ratio)), 9),
        "high_freq_ratio": round(float(high_freq_ratio), 9),
        "high_frequency_ratio": round(float(high_freq_ratio), 9),
        "transient": round(float(transient), 9),
        "transient_score": round(float(transient), 9),
        "glitch_score": round(float(glitch_score), 9),
    }


def _input_channel_indices(input_channels: Sequence[int]) -> tuple[int, int]:
    if len(input_channels) != 2:
        raise ValueError("expected exactly two ES-9 input channels")
    left, right = (int(input_channels[0]), int(input_channels[1]))
    if left < 1 or right < 1:
        raise ValueError("ES-9 input channels are 1-based and must be >= 1")
    return left - 1, right - 1


def _select_stereo_inputs(indata: np.ndarray | None, input_channels: Sequence[int]) -> np.ndarray | None:
    left_idx, right_idx = _input_channel_indices(input_channels)
    if indata is None or indata.ndim != 2 or indata.shape[0] == 0:
        return None
    if indata.shape[1] <= max(left_idx, right_idx):
        return None
    return np.asarray(indata[:, [left_idx, right_idx]], dtype=np.float32)


def measure_input_audio(
    indata: np.ndarray | None,
    *,
    blocks: int = 0,
    sample_rate: int = 48_000,
    previous_peak: float = 0.0,
    input_channels: Sequence[int] = (1, 2),
) -> dict[str, Any]:
    """Return selected ES-9 input-pair RMS/peak plus frequency/glitch telemetry."""

    source_channels = [int(input_channels[0]), int(input_channels[1])]
    empty = {
        "source_input_channels": source_channels,
        "input_1_rms": 0.0,
        "input_2_rms": 0.0,
        "input_1_peak": 0.0,
        "input_2_peak": 0.0,
        "blocks": int(blocks),
        **analyze_audio_block(None, sample_rate=sample_rate, previous_peak=previous_peak),
    }
    stereo = _select_stereo_inputs(indata, input_channels)
    if stereo is None:
        return empty
    rms = np.sqrt(np.mean(np.square(stereo), axis=0))
    peak = np.max(np.abs(stereo), axis=0)
    features = analyze_audio_block(stereo, sample_rate=sample_rate, previous_peak=previous_peak)
    return {
        "source_input_channels": source_channels,
        "input_1_rms": round(float(rms[0]), 9),
        "input_2_rms": round(float(rms[1]), 9),
        "input_1_peak": round(float(peak[0]), 9),
        "input_2_peak": round(float(peak[1]), 9),
        "blocks": int(blocks),
        **features,
    }


def fill_output_block(
    outdata: np.ndarray,
    indata: np.ndarray | None,
    cv_values: Sequence[float],
    *,
    main_gain: float,
    input_channels: Sequence[int] = (1, 2),
) -> None:
    """Fill a 16-channel output block with selected stereo audio + DC CV."""

    if outdata.ndim != 2:
        raise ValueError("outdata must be frames x channels")
    if outdata.shape[1] < 16:
        raise ValueError("ES-9 output stream must expose at least 16 channels")
    if len(cv_values) != 8:
        raise ValueError("expected 8 physical ES-9 CV values")

    outdata.fill(0.0)

    stereo = _select_stereo_inputs(indata, input_channels)
    if stereo is not None:
        gain = float(np.clip(main_gain, 0.0, 2.0))
        outdata[:, 0] = np.clip(stereo[:, 0] * gain, -0.98, 0.98)
        outdata[:, 1] = np.clip(stereo[:, 1] * gain, -0.98, 0.98)

    for physical_index, value in enumerate(cv_values, start=1):
        ch = physical_cv_to_coreaudio_channel(physical_index)
        outdata[:, ch] = float(np.clip(value, -1.0, 1.0))


def find_sounddevice_index(name_contains: str, *, need_inputs: int = 16, need_outputs: int = 16) -> int:
    import sounddevice as sd

    needle = name_contains.lower()
    for idx, dev in enumerate(sd.query_devices()):
        if needle in dev["name"].lower() and dev["max_input_channels"] >= need_inputs and dev["max_output_channels"] >= need_outputs:
            return idx
    available = [f"{i}: {d['name']} ({d['max_input_channels']} in/{d['max_output_channels']} out)" for i, d in enumerate(sd.query_devices())]
    raise RuntimeError(f"No device matching {name_contains!r} with {need_inputs} inputs/{need_outputs} outputs. Available: {available}")


def fetch_camera_image(url: str, timeout: float = 0.75) -> Image.Image:
    import requests

    resp = requests.get(url, timeout=timeout)
    resp.raise_for_status()
    return Image.open(io.BytesIO(resp.content)).convert("RGB")


def status_dict(
    *,
    ok: bool,
    device: str,
    sample_rate: int,
    blocksize: int,
    main_gain: float,
    max_cv: float,
    vision_mode: str,
    features: CameraFeatures,
    cv_values: Sequence[float],
    frames_seen: int,
    person_scene: PersonScene | None = None,
    audio_input: dict[str, Any] | None = None,
    preview_path: str | None = None,
    chord: dict | None = None,
    error: str | None = None,
) -> dict:
    status = BridgeStatus(
        ok=ok,
        timestamp=time.time(),
        device=device,
        sample_rate=sample_rate,
        blocksize=blocksize,
        main_gain=main_gain,
        max_cv=max_cv,
        vision_mode=vision_mode,
        features=features,
        cv={label: round(float(value), 6) for label, value in zip(CV_LABELS, cv_values)},
        coreaudio_outputs={label: physical_cv_to_coreaudio_channel(i) + 1 for i, label in enumerate(CV_LABELS, start=1)},
        frames_seen=frames_seen,
        person_scene=person_scene,
        audio_input=audio_input,
        preview_path=preview_path,
        error=error,
    )
    data = asdict(status)
    # Active chord (voicing name, root, voice offsets) surfaced for the
    # reviewer agent + remote operator. Mirrors what the live mappers are
    # actually using right now (post-transition-blend if mid-crossfade).
    if chord is not None:
        data["chord"] = {
            "voicing": chord.get("voicing"),
            "root_semitones": chord.get("root_semitones"),
            "voice_offsets": list(chord.get("voice_offsets", ())) or None,
            "smoothing_hz": chord.get("smoothing_hz"),
            "pitch_wander_scale": chord.get("pitch_wander_scale"),
            "transition_seconds": chord.get("transition_seconds"),
            "transition_progress": chord.get("_transition_progress"),
        }
    data["note"] = "CoreAudio outputs are 1-based here: ES-9 physical CV outs 1-8 = CoreAudio outs 9-16."
    return data


def write_json_atomic(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")
    tmp.replace(path)


def write_image_atomic(path: Path, image: Image.Image, *, quality: int = 86) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    image.save(tmp, format="JPEG", quality=quality)
    tmp.replace(path)


def _clamp01(value: float) -> float:
    return float(np.clip(float(value), 0.0, 1.0))


def _slew_targets(
    targets: Sequence[float],
    *,
    current_attr: str,
    owner: Any,
    max_cv: float,
    smoothing_hz: float,
    dt: float,
    per_channel_smoothing_hz: Sequence[float] | None = None,
) -> list[float]:
    """Exponential one-pole slew toward each target.

    smoothing_hz is the default 1-pole cutoff applied to every channel.
    per_channel_smoothing_hz, when provided, overrides per index — letting
    fast-reactive controls (mix VCA, glitch gate) track scene changes
    quickly while chord voices stay glacial. Length must match targets.
    """
    clipped = [float(np.clip(v, 0.0, max_cv)) for v in targets]
    current = getattr(owner, current_attr)
    if current is None:
        setattr(owner, current_attr, clipped)
    else:
        rates: Sequence[float]
        if per_channel_smoothing_hz is not None and len(per_channel_smoothing_hz) == len(clipped):
            rates = per_channel_smoothing_hz
        else:
            rates = [smoothing_hz] * len(clipped)
        new_state: list[float] = []
        for old, new, hz in zip(current, clipped, rates):
            if dt <= 0.0:
                alpha = 1.0
            else:
                alpha = 1.0 - math.exp(float(-hz) * dt)
            alpha = float(np.clip(alpha, 0.0, 1.0))
            new_state.append(old + (new - old) * alpha)
        setattr(owner, current_attr, new_state)
    return [float(np.clip(v, 0.0, max_cv)) for v in getattr(owner, current_attr)]


def build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Route SWN through ES-9 and modulate SWN CV from Lisbon camera frames.")
    p.add_argument("--device", default="ES-9", help="sounddevice/CoreAudio device name substring")
    p.add_argument("--camera-url", default="http://127.0.0.1:8765/frame.jpg")
    p.add_argument("--status-path", default="audio/runtime/swn_camera_soundscape_status.json")
    p.add_argument("--preview-path", default="audio/runtime/swn_camera_people_preview.jpg")
    p.add_argument("--sample-rate", type=int, default=48000)
    p.add_argument("--blocksize", type=int, default=128)
    p.add_argument("--camera-hz", type=float, default=4.0)
    p.add_argument("--status-hz", type=float, default=60.0, help="status JSON write rate; keep higher than camera_hz so audio telemetry reaches lights with low latency")
    p.add_argument("--main-gain", type=float, default=0.55, help="selected rack/SWN input-pair gain to main outputs 1/2")
    p.add_argument("--input-left-channel", type=int, default=1, help="1-based ES-9/CoreAudio input channel to monitor/route as left")
    p.add_argument("--input-right-channel", type=int, default=2, help="1-based ES-9/CoreAudio input channel to monitor/route as right")
    p.add_argument("--max-cv", type=float, default=0.25, help="normalized ES-9 CV ceiling; 0.25 is roughly +2.5 V if calibrated 1.0=10 V")
    p.add_argument("--smoothing-hz", type=float, default=6.0)
    p.add_argument("--stillness-deadband", type=float, default=0.03, help="normalized person-center jitter below this is treated as stillness so CV does not wobble from detector noise")
    p.add_argument("--stillness-frame-motion", type=float, default=0.03, help="aggregate frame-difference motion below this holds person CV steady even if YOLO boxes jitter")
    p.add_argument("--duration", type=float, default=0.0, help="seconds to run; 0 means until stopped")
    p.add_argument("--dry-run", action="store_true", help="poll camera and write status without opening ES-9 audio stream")
    p.add_argument("--vision-mode", choices=("aggregate", "people"), default="people", help="aggregate uses frame brightness/motion; people uses YOLO+ByteTrack scene features")
    p.add_argument("--yolo-model", default="yolo11n.pt", help="Ultralytics model name/path for --vision-mode people")
    p.add_argument("--yolo-conf", type=float, default=0.25, help="YOLO confidence threshold; lower = more sensitive (default 0.25)")
    p.add_argument("--yolo-tracker", default="bytetrack.yaml")
    p.add_argument("--yolo-imgsz", type=int, default=480, help="YOLO inference image size; lower = faster (default 480, ~4x speedup vs 1080p)")
    p.add_argument("--tracker-max-missing", type=int, default=16, help="frames a track survives without re-detection before being culled (default 16 = 8s at camera_hz=2)")
    p.add_argument("--tracker-match-threshold", type=float, default=0.24, help="centroid distance threshold for nearest-neighbor re-matching")
    p.add_argument("--preview-hz", type=float, default=2.0, help="annotated preview write rate in people mode; <=0 disables")
    p.add_argument("--scene-port", type=int, default=8768, help="HTTP port to serve the annotated scene preview (0 disables)")
    p.add_argument("--scene-host", default="127.0.0.1", help="interface to bind the scene server (default 127.0.0.1, exposed via Tailscale serve)")
    return p


def main(argv: Sequence[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    input_channels = (args.input_left_channel, args.input_right_channel)
    _input_channel_indices(input_channels)
    status_path = Path(args.status_path)
    preview_path = Path(args.preview_path) if args.preview_path and args.preview_hz > 0 else None
    feature_tracker = CameraFeatureTracker()
    aggregate_mapper = LisbonSwnMapper(max_cv=args.max_cv, smoothing_hz=args.smoothing_hz)
    person_tracker = PersonSceneTracker(
        max_missing=args.tracker_max_missing,
        match_threshold=args.tracker_match_threshold,
        stillness_deadband=args.stillness_deadband,
    )
    human_mapper = HumanAwareSwnMapper(max_cv=args.max_cv, smoothing_hz=args.smoothing_hz)
    initial_scene = person_tracker.update([], frame_size=(1, 1), dt=0.0)
    initial_cv = (
        human_mapper.step_scene(initial_scene, dt=0.0)
        if args.vision_mode == "people"
        else aggregate_mapper.step(brightness=0.0, motion=0.0, centroid_x=0.5, centroid_y=0.5, dt=0.0)
    )

    # Live profile poller — reads heuristic_profile.json once per second and
    # pushes the resolved chord block into both mappers. Slow loop owns the
    # chord; fast loop slews to the new V/oct targets smoothly via
    # smoothing_hz. If the profile is missing, malformed, or expired, the
    # mappers fall back to the hardcoded open-fifth.
    #
    # Same dual-import dance as the module-level helpers: the bridge runs
    # as `python audio/lisbon_swn_camera_bridge.py` with cwd at project
    # root, which puts `audio/` on sys.path (not the project root), so
    # `import audio.chord_palette` fails. Fall back to bare `chord_palette`.
    resolve_chord = None
    try:
        from audio.chord_palette import resolve_chord  # type: ignore
    except Exception:
        try:
            from chord_palette import resolve_chord  # type: ignore
        except Exception:
            resolve_chord = None  # bridge still works without the palette module

    profile_path = status_path.parent / "heuristic_profile.json"
    # 6/4 r16: tune knobs live in their own file to avoid the read-modify-
    # write race that used to clobber `tune` updates when both tune.py and
    # the realtime chord driver touched heuristic_profile.json. Polled
    # independently from the chord profile; nothing else writes here.
    tune_path = status_path.parent / "tune.json"
    profile_state: dict[str, Any] = {"mtime": 0.0, "tune_mtime": 0.0, "chord": None, "tune_warned_legacy": False}

    def _apply_tune(tune: dict) -> None:
        """Push a tune dict into both detector and mapper. Silent if the
        dict is empty; per-key set_tuning methods skip unchanged values.
        """
        if not isinstance(tune, dict) or not tune:
            return
        try:
            person_tracker.set_tuning(
                stillness_deadband=tune.get("stillness_deadband"),
                match_threshold=tune.get("tracker_match_threshold"),
                movement_source=tune.get("movement_source"),
                postural_confidence_floor=tune.get("postural_confidence_floor"),
                postural_ema_alpha=tune.get("postural_ema_alpha"),
            )
        except Exception as exc:
            print(f"[poll] tune tracker error: {exc!r}", flush=True)
        try:
            human_mapper.set_tuning(
                glitch_fire_threshold=tune.get("glitch_fire_threshold"),
                browse_rate_min_hz=tune.get("browse_rate_min_hz"),
                browse_rate_max_hz=tune.get("browse_rate_max_hz"),
                cv7_hold_ms=tune.get("cv7_hold_ms"),
                cv7_release_ms=tune.get("cv7_release_ms"),
            )
        except Exception as exc:
            print(f"[poll] tune mapper error: {exc!r}", flush=True)

    def poll_profile_loop() -> None:
        while not stop.is_set():
            # --- tune.json (isolated, written only by scripts/tune.py) ---
            try:
                if tune_path.exists():
                    tstat = tune_path.stat()
                    if tstat.st_mtime != profile_state["tune_mtime"]:
                        profile_state["tune_mtime"] = tstat.st_mtime
                        tune_data = json.loads(tune_path.read_text(encoding="utf-8"))
                        if isinstance(tune_data, dict):
                            _apply_tune(tune_data)
            except (OSError, json.JSONDecodeError) as exc:
                print(f"[poll] tune.json io/json error: {exc!r}", flush=True)
            except Exception as exc:
                print(f"[poll] tune.json UNEXPECTED ERROR: {exc!r}", flush=True)

            # --- heuristic_profile.json (chord layer, written by realtime driver) ---
            try:
                stat = profile_path.stat()
                if stat.st_mtime != profile_state["mtime"]:
                    profile_state["mtime"] = stat.st_mtime
                    data = json.loads(profile_path.read_text(encoding="utf-8"))
                    expires_at = data.get("expires_at")
                    expired = False
                    if isinstance(expires_at, str):
                        try:
                            expiry = datetime.fromisoformat(expires_at.replace("Z", "+00:00"))
                            expired = datetime.now(tz=timezone.utc) > expiry
                        except Exception:
                            expired = False
                    # Back-compat: pre-r16 tune values lived inside the
                    # profile. If we still see one, apply it (low priority,
                    # tune.json takes precedence by virtue of running after)
                    # and warn ONCE so the operator migrates.
                    legacy_tune = data.get("tune") if isinstance(data.get("tune"), dict) else {}
                    if legacy_tune and not profile_state["tune_warned_legacy"]:
                        print(
                            "[poll] WARN legacy `tune` block in heuristic_profile.json — "
                            "re-run scripts/tune.py to migrate to audio/runtime/tune.json",
                            flush=True,
                        )
                        profile_state["tune_warned_legacy"] = True
                    if legacy_tune and not tune_path.exists():
                        _apply_tune(legacy_tune)
                    if not expired and resolve_chord is not None:
                        chord = resolve_chord(data.get("chord"))
                        profile_state["chord"] = chord
                        aggregate_mapper.set_chord(chord)
                        human_mapper.set_chord(chord)
                        # Log once per successful poll so deployment errors
                        # are surfaceable from launchd logs.
                        print(f"[poll] chord set: {chord.get('voicing')}@{chord.get('root_semitones'):.1f}", flush=True)
                    else:
                        profile_state["chord"] = None
                        aggregate_mapper.set_chord(None)
                        human_mapper.set_chord(None)
                        print(f"[poll] chord cleared (expired={expired}, has_resolver={resolve_chord is not None})", flush=True)
            except (OSError, json.JSONDecodeError) as exc:
                # No profile yet, or unreadable — mappers keep last good chord.
                print(f"[poll] expected io/json error: {exc!r}", flush=True)
            except Exception as exc:
                # Anything else (KeyError, AttributeError, import-deferred
                # NameError, etc.) was previously dropped silently and made
                # the chord layer look broken. Surface it.
                print(f"[poll] UNEXPECTED ERROR: {exc!r}", flush=True)
            stop.wait(1.0)
    detector: YoloByteTrackPersonDetector | None = None
    lock = threading.Lock()
    stop = threading.Event()
    state = {
        "features": CameraFeatures(0.0, 0.0, 0.5, 0.5),
        "person_scene": initial_scene,
        "cv": initial_cv,
        "frames_seen": 0,
        "audio_input": measure_input_audio(None, blocks=0, input_channels=input_channels),
        "error": None,
    }

    def handle_signal(_signum, _frame) -> None:
        stop.set()

    signal.signal(signal.SIGINT, handle_signal)
    signal.signal(signal.SIGTERM, handle_signal)

    def camera_loop() -> None:
        nonlocal detector
        last = time.monotonic()
        last_preview = 0.0
        interval = 1.0 / max(0.1, args.camera_hz)
        preview_interval = 1.0 / max(0.1, args.preview_hz) if preview_path is not None else float("inf")
        # Per-track frame counter — how many frames a given id has been
        # continuously seen. Used by annotate_person_scene to surface "age"
        # in the preview overlay so the operator can see track stability.
        track_ages: dict[int, int] = {}
        while not stop.is_set():
            now = time.monotonic()
            dt = max(0.0, now - last)
            last = now
            try:
                img = fetch_camera_image(args.camera_url)
                features = feature_tracker.update(img)
                scene = state["person_scene"]
                if args.vision_mode == "people":
                    if detector is None:
                        detector = YoloByteTrackPersonDetector(args.yolo_model, confidence=args.yolo_conf, tracker=args.yolo_tracker, imgsz=args.yolo_imgsz)
                    observations = detector.detect(img)
                    scene = person_tracker.update(observations, frame_size=img.size, dt=dt)
                    # Update track age counters: increment seen ids, drop ones that disappeared.
                    seen_ids = {t.id for t in scene.tracks}
                    for tid in list(track_ages.keys()):
                        if tid not in seen_ids:
                            del track_ages[tid]
                    for tid in seen_ids:
                        track_ages[tid] = track_ages.get(tid, 0) + 1
                    if hold_person_cv_for_still_frame(features, scene, frame_motion_threshold=args.stillness_frame_motion):
                        scene = quiet_person_scene(scene)
                        with lock:
                            previous_cv = list(state["cv"])
                        cv_values = human_mapper.step_movement_gate_only(scene, previous_cv, dt=dt)
                    else:
                        cv_values = human_mapper.step_scene(scene, dt=dt)
                    if preview_path is not None and now - last_preview >= preview_interval:
                        chord_label = None
                        chord = profile_state.get("chord")
                        if isinstance(chord, dict):
                            voicing = chord.get("voicing")
                            root = chord.get("root_semitones")
                            if voicing and isinstance(root, (int, float)):
                                chord_label = f"{voicing}@{root:.0f}"
                        annotated = annotate_person_scene(img, scene, chord_label=chord_label, track_ages=track_ages)
                        # Downscale to 720p max width before save — cuts JPEG
                        # bytes ~4x so browser at 10Hz polling sees fluid motion
                        # over Tailscale instead of buffering 175KB frames.
                        max_w = 1280
                        if annotated.width > max_w:
                            ratio = max_w / annotated.width
                            annotated = annotated.resize(
                                (max_w, int(annotated.height * ratio)),
                                Image.BILINEAR,
                            )
                        write_image_atomic(preview_path, annotated, quality=75)
                        last_preview = now
                else:
                    cv_values = aggregate_mapper.step(
                        brightness=features.brightness,
                        motion=features.motion,
                        centroid_x=features.centroid_x,
                        centroid_y=features.centroid_y,
                        dt=dt,
                    )
                with lock:
                    state["features"] = features
                    state["person_scene"] = scene
                    state["cv"] = cv_values
                    state["frames_seen"] = int(state["frames_seen"]) + 1
                    state["error"] = None
            except Exception as exc:  # keep audio safe/running if the camera or detector hiccups
                with lock:
                    state["error"] = repr(exc)
            # Adaptive throttle: only sleep if we finished the iteration
            # faster than the target interval. If YOLO took longer, loop
            # immediately so we run as fast as the detector allows.
            elapsed = time.monotonic() - now
            remaining = interval - elapsed
            if remaining > 0.001:
                stop.wait(remaining)

    def snapshot_status() -> dict[str, Any]:
        with lock:
            # Surface the active (post-transition-blend) chord from whichever
            # mapper is actually driving CV. This gives the reviewer agent
            # and the /scene/ overlay the truth on the wire.
            mapper = human_mapper if args.vision_mode == "people" else aggregate_mapper
            active_chord = mapper._active_chord()
            return status_dict(
                ok=state["error"] is None,
                device=args.device,
                sample_rate=args.sample_rate,
                blocksize=args.blocksize,
                main_gain=args.main_gain,
                max_cv=args.max_cv,
                vision_mode=args.vision_mode,
                features=state["features"],
                cv_values=state["cv"],
                frames_seen=int(state["frames_seen"]),
                person_scene=state["person_scene"],
                audio_input=state["audio_input"],
                preview_path=str(preview_path) if preview_path is not None else None,
                chord=active_chord,
                error=state["error"],
            )

    def status_loop() -> None:
        interval = 1.0 / max(1.0, args.status_hz)
        while not stop.is_set():
            write_json_atomic(status_path, snapshot_status())
            stop.wait(interval)

    camera_thread = threading.Thread(target=camera_loop, name="camera-cv-loop", daemon=True)
    status_thread = threading.Thread(target=status_loop, name="status-json-loop", daemon=True)
    profile_thread = threading.Thread(target=poll_profile_loop, name="heuristic-profile-poll", daemon=True)
    camera_thread.start()
    status_thread.start()
    profile_thread.start()

    # Optional: start the HTTP scene preview server when a preview file is
    # being written and the operator hasn't disabled the port. Designed to
    # land behind Tailscale serve at /scene/ for remote operator monitoring.
    scene_server: SceneServer | None = None
    if preview_path is not None and args.scene_port > 0:
        try:
            scene_server = SceneServer(
                args.scene_port,
                preview_path,
                host=args.scene_host,
                status_path=status_path,
                room_audio_path=status_path.parent / "room_audio_probe_status.json",
            )
            scene_server.start()
        except OSError as exc:
            print(f"  scene server: failed to bind {args.scene_host}:{args.scene_port} ({exc})")
            scene_server = None

    print("Lisbon SWN camera soundscape")
    print(f"  camera: {args.camera_url}")
    print(f"  status: {status_path}")
    print(f"  vision: {args.vision_mode}")
    if preview_path is not None:
        print(f"  preview: {preview_path}")
    if scene_server is not None:
        print(f"  scene server: http://{args.scene_host}:{args.scene_port}/  (path-scope behind Tailscale serve at /scene/)")
    print(f"  input pair: ES-9/CoreAudio inputs {input_channels[0]}/{input_channels[1]} -> main outputs 1/2 + analysis")
    print("  routing: USB/CoreAudio outputs 1/2 -> ES-9 main mix path; physical CV outs 1-8 -> CoreAudio outs 9-16")
    print("  CV map:")
    for i, label in enumerate(CV_LABELS, start=1):
        print(f"    ES-9 CV{i} / CoreAudio out {physical_cv_to_coreaudio_channel(i)+1}: {label}")

    start = time.monotonic()
    if args.dry_run:
        while not stop.is_set() and (args.duration <= 0 or time.monotonic() - start < args.duration):
            time.sleep(0.1)
        stop.set()
        camera_thread.join(timeout=2.0)
        status_thread.join(timeout=2.0)
        if scene_server is not None:
            scene_server.stop()
        return 0

    import sounddevice as sd

    device_index = find_sounddevice_index(args.device)
    print(f"  audio device: #{device_index} {sd.query_devices(device_index)['name']}")

    def callback(indata, outdata, frames, time_info, status) -> None:  # noqa: ANN001
        if status:
            # Keep callback realtime-safe: expose the status in the JSON path from the main loop if needed.
            pass
        with lock:
            blocks = int(state["audio_input"].get("blocks", 0)) + 1
            previous_peak = float(state["audio_input"].get("stereo_peak", 0.0))
            state["audio_input"] = measure_input_audio(
                indata,
                blocks=blocks,
                sample_rate=args.sample_rate,
                previous_peak=previous_peak,
                input_channels=input_channels,
            )
            cv_values = list(state["cv"])
        fill_output_block(outdata, indata, cv_values, main_gain=args.main_gain, input_channels=input_channels)

    with sd.Stream(
        device=(device_index, device_index),
        samplerate=args.sample_rate,
        blocksize=args.blocksize,
        channels=(16, 16),
        dtype="float32",
        latency="low",
        callback=callback,
    ):
        while not stop.is_set() and (args.duration <= 0 or time.monotonic() - start < args.duration):
            time.sleep(0.1)

    stop.set()
    camera_thread.join(timeout=2.0)
    status_thread.join(timeout=2.0)
    if scene_server is not None:
        scene_server.stop()
    final = snapshot_status()
    write_json_atomic(status_path, final)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
