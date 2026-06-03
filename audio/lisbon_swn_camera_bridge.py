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
    "cv5_dispersion",
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
# Live tuning 2026-06-03: operator reported volume control feels laggy
# and distance doesn't track presence. Boosted mix VCA + glitch.
PER_CV_SMOOTHING_HZ = [
    6.0,    # cv1 voice1 1v/oct  — chord pitch, slow
    6.0,    # cv2 voice2 1v/oct
    6.0,    # cv3 voice3 1v/oct
    10.0,   # cv4 wavetable browse
    10.0,   # cv5 dispersion
    18.0,   # cv6 main mix VCA   — fast, tracks presence
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
    """One raw person detection from YOLO/ByteTrack."""

    track_id: int | None
    bbox_xyxy: tuple[float, float, float, float]
    confidence: float = 1.0


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


class PersonSceneTracker:
    """Stable ID and scene summary layer for person detections.

    Ultralytics/ByteTrack supplies IDs when it can. When it cannot, this class
    does conservative nearest-centroid matching so the musical voices do not
    randomly reassign every frame.
    """

    def __init__(self, max_missing: int = 8, match_threshold: float = 0.24, stillness_deadband: float = 0.03) -> None:
        self.max_missing = max(0, int(max_missing))
        self.match_threshold = float(match_threshold)
        self.stillness_deadband = max(0.0, float(stillness_deadband))
        self._tracks: dict[int, _TrackMemory] = {}
        self._next_id = 1

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
            track_id = int(obs.track_id) if obs.track_id is not None else self._match_or_allocate(metrics["center_x"], metrics["center_y"], active_ids)
            previous = self._tracks.get(track_id)
            if previous is None:
                movement = 0.0
                age = 1
            else:
                delta = math.hypot(metrics["center_x"] - previous.center_x, metrics["center_y"] - previous.center_y)
                if delta <= self.stillness_deadband:
                    metrics = {
                        "width": previous.width,
                        "height": previous.height,
                        "area": previous.area,
                        "center_x": previous.center_x,
                        "center_y": previous.center_y,
                        "distance": previous.distance,
                    }
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
        movement = float(np.average(movements, weights=weights))
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


def observations_from_yolo_result(result: Any, *, min_confidence: float = 0.35) -> list[PersonObservation]:
    """Extract person observations from one Ultralytics YOLO/ByteTrack result."""

    boxes = getattr(result, "boxes", None)
    if boxes is None:
        return []

    xyxy = _to_numpy(getattr(boxes, "xyxy", None))
    if xyxy is None or xyxy.size == 0:
        return []

    conf = _to_numpy(getattr(boxes, "conf", None))
    cls = _to_numpy(getattr(boxes, "cls", None))
    ids = _to_numpy(getattr(boxes, "id", None))
    observations: list[PersonObservation] = []

    for i, raw_bbox in enumerate(np.asarray(xyxy).reshape((-1, 4))):
        confidence = 1.0 if conf is None or len(conf) <= i else float(conf[i])
        class_id = 0 if cls is None or len(cls) <= i else int(cls[i])
        if class_id != 0 or confidence < min_confidence:
            continue
        if ids is None or len(ids) <= i or np.isnan(float(ids[i])):
            track_id = None
        else:
            track_id = int(ids[i])
        bbox = tuple(round(float(v), 3) for v in raw_bbox)
        observations.append(PersonObservation(track_id=track_id, bbox_xyxy=bbox, confidence=round(confidence, 6)))
    return observations


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
        label = f"id {track.id}{age_str} {track.confidence:.2f} d{track.distance:.2f} v{track.movement:.2f}"
        text_box = draw.textbbox((x1, max(0, y1 - 14)), label)
        draw.rectangle(text_box, fill=(0, 0, 0))
        draw.text((x1, max(0, y1 - 14)), label, fill=color)
        cx = int(round(track.center_x * width))
        cy = int(round(track.center_y * height))
        draw.ellipse((cx - 3, cy - 3, cx + 3, cy + 3), outline=color, width=line_w)

    summary = (
        f"people {scene.people_count}  activity {scene.activity:.2f}  "
        f"near {scene.nearest_distance:.2f}  spread {scene.spread_x:.2f}"
    )
    if chord_label:
        summary = f"{summary}  chord {chord_label}"
    bar_w = min(width, max(520, 9 * len(summary)))
    draw.rectangle((0, 0, bar_w, 22), fill=(0, 0, 0))
    draw.text((6, 4), summary, fill=(255, 255, 255))
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
            "  #panel{position:fixed;right:8px;top:8px;bottom:8px;width:380px;background:rgba(0,0,0,.78);border:1px solid #333;padding:12px;font-size:11px;overflow-y:auto;line-height:1.55}\n"
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
            "    h+=row('cv5 disp',cv.cv5_dispersion,mx);\n"
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
        return observations_from_yolo_result(results[0], min_confidence=self.confidence)


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
            (root_semi + voice_offsets[1]) * semitone + pitch_wander * 0.7,
            (root_semi + voice_offsets[2]) * semitone + pitch_wander * 0.45,
            0.025 + 0.165 * ((centroid_x * 0.65) + (activity * 0.35)),  # browse
            0.020 + 0.190 * motion,  # dispersion
            self.max_cv * mix_target,  # CV6 main mix VCA
            0.0 if motion <= 0.005 else self.max_cv * (_clamp01(motion * 2.6) ** 0.55),  # CV7 glitch trigger (sensitivity tuned 6/3)
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
        self._current: list[float] | None = None
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

    def _movement_gate_target(self, scene: PersonScene) -> float:
        movement = max(_clamp01(scene.movement), _clamp01(scene.activity))
        if movement <= 0.005:
            return 0.0
        # Open the gate with a curved response so small real motion is audible,
        # but detector noise below the stillness gates remains fully closed.
        # Tuned (2026-06-03 live test): operator feedback "glitch needs a
        # touch more sensitivity for movement". Bumped multiplier 1.85 -> 2.6
        # and softened exponent 0.7 -> 0.55 so a casual walk lands around
        # 0.4-0.6 of max_cv instead of 0.2-0.3. The max_cv ceiling still
        # caps the absolute level.
        gate = _clamp01(movement * 2.6) ** 0.55
        return float(np.clip(self.max_cv * gate, 0.0, self.max_cv))

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
        targets[MOVEMENT_GATE_CV_INDEX] = self._movement_gate_target(scene)
        # CV6 main mix VCA — keep it responsive to presence during stillness,
        # same math as the live path in step_scene.
        mean_distance = _clamp01(scene.mean_distance)
        count = _clamp01(scene.count_norm)
        activity = _clamp01(scene.activity)
        presence = 0.65 * mean_distance + 0.20 * count + 0.15 * activity
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
        presence = (
            0.65 * mean_distance       # primary: closeness drives loudness
            + 0.20 * count             # secondary: more bodies, slight boost
            + 0.15 * activity          # tertiary: motion swell
        )
        mix_target = 0.00 + 1.00 * _clamp01(presence)
        targets = [
            (root_semi + voice_offsets[0]) * semitone + pitch_wander,
            (root_semi + voice_offsets[1]) * semitone + pitch_wander * 0.65,
            (root_semi + voice_offsets[2]) * semitone + pitch_wander * 0.42,
            0.025 + 0.165 * (0.62 * x + 0.23 * spread + 0.15 * activity),
            0.015 + 0.185 * (0.50 * mean_distance + 0.25 * count + 0.25 * activity),
            self.max_cv * mix_target,
            self._movement_gate_target(scene),
            0.025 + 0.185 * (0.68 * nearest + 0.22 * activity + 0.10 * movement),
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
    profile_state: dict[str, Any] = {"mtime": 0.0, "chord": None}

    def poll_profile_loop() -> None:
        while not stop.is_set():
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
                        write_image_atomic(
                            preview_path,
                            annotate_person_scene(img, scene, chord_label=chord_label, track_ages=track_ages),
                        )
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
