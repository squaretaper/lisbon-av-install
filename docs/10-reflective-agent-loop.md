# Reflective Agent Loop — Fast Reflex, Slow Metabolism

## Thesis

The Lisbon system should not put an LLM/agent directly in the realtime audio/CV/light reflex arc.

Use two loops:

```text
fast loop  = embodied, deterministic, realtime
slow loop  = reflective, adaptive, agentic
```

The fast loop decides what happens in the next 10–500 ms. The slow loop reviews what has been happening over minutes and updates compact heuristics that the fast loop can perform safely.

Short version: **the agent should not be in the reflex arc; it should be in the metabolism.**

## Why this exists

Putting an agent call inside each sense/respond cycle creates the wrong failure modes for an installation:

- latency becomes perceptible and variable;
- internet/model/provider outages become show outages;
- hallucinated or malformed output can hit audio, CV, or lights;
- repeated calls are expensive and hard to debug;
- the work becomes brittle exactly when visitors are interacting with it.

The better architecture is:

```text
camera/audio/sensors
        ↓
fast local heuristic/state machine
        ↓
immediate sound/CV/light behavior
        ↓
telemetry/event log/status JSON
        ↓
periodic reflective review
        ↓
small parameter/profile update
        ↓
fast local heuristic/state machine
```

## Current Lisbon mapping

The existing live bridge already has most of the fast-loop pieces:

- camera bridge → person/scene features;
- ES-9 audio input → RMS/peak/FFT/glitch telemetry;
- Python bridge → ES-9 output 1/2 main audio and ES-9 CV outputs 9–16;
- ESP32 serial bridge → red-only lighting modes, brightness, chase speed, pulse depth, packet span;
- status file: `audio/runtime/swn_camera_soundscape_status.json`.

The reflective loop should sit above these pieces. It should read telemetry and write a small control profile, not touch audio buffers, serial timing, CoreAudio callbacks, or raw CV output directly.

## Responsibilities split

### Fast loop owns

- camera frame acquisition and person tracking;
- smoothed scene features: person count, movement, stillness, sector activity;
- audio telemetry: RMS/peak, dominant frequency, spectral centroid, band ratios, transient/glitch evidence;
- bounded CV mapping to SWN/O&C;
- main mix gain/limiting and ES-9 routing;
- lighting commands at low latency;
- watchdogs and `/api/silence` behavior;
- hard clamps for audio gain, CV voltage, brightness, and serial command rate.

### Slow reflective loop owns

- reviewing recent telemetry windows every ~2–10 minutes;
- detecting stuck states, overactivity, deadness, or visitor disengagement;
- nudging mode bias, sensitivity, density, silence, and motif selection;
- suggesting but not directly performing larger patch/config changes;
- writing a versioned, bounded `heuristic_profile` consumed by the fast loop;
- logging the reason for each change for post-show review.

## Control profile contract

The slow loop writes an atomic JSON file, for example:

```text
audio/runtime/heuristic_profile.json
```

A non-live example lives at:

```text
audio/heuristic_profile.example.json
```

Suggested shape:

```json
{
  "schema": "lisbon.heuristic_profile.v1",
  "updated_at": "2026-05-28T14:00:00Z",
  "expires_at": "2026-05-28T14:10:00Z",
  "source": "reflective_agent",
  "profile_id": "late-gallery-sparse-001",
  "reason": "Room has been still for 7 minutes; keep drone sparse, lower glitch probability, preserve responsiveness to real movement.",
  "mode_bias": "sparse_drone",
  "scene": {
    "silence_hold_seconds": 18,
    "density_target": 0.28,
    "avoid_repetition_seconds": 90
  },
  "camera": {
    "movement_gate_sensitivity": 0.42,
    "stillness_deadband_scale": 1.0,
    "sector_activity_weight": 0.65
  },
  "audio": {
    "drone_bias": 0.58,
    "glitch_probability": 0.06,
    "high_band_strobe_threshold_scale": 1.1,
    "feedback_suppression": 0.8
  },
  "lights": {
    "brightness_ceiling": 176,
    "black_floor_bias": 0.55,
    "strobe_ceiling": 240,
    "packet_complexity": 0.7
  },
  "cv": {
    "max_cv_scale": 1.0,
    "movement_gate_ceiling_v": 4.5,
    "pitch_drift_scale": 0.5
  }
}
```

Fast-loop consumers must treat this as advisory and clamp everything. If the file is missing, expired, malformed, or out of range, ignore it and continue with safe local defaults.

## Update rules

The reflective loop may update these classes of parameters:

- mode bias: sparse/dense/drone/glitch/rest;
- movement sensitivity and stillness hold time;
- density target and repetition avoidance;
- brightness ceilings and black/off bias;
- glitch probability and strobe thresholds;
- packet complexity/chase feel;
- CV scaling within pre-approved safe limits.

The reflective loop must not update:

- ES-9 physical channel map;
- CV output destinations;
- CoreAudio device index or channel count;
- serial port name;
- firmware mode semantics;
- raw gain beyond hardcoded ceilings;
- anything requiring a patch-cable change;
- live code.

## Review cadence

Suggested cadence for Lisbon:

| Loop | Cadence | Implementation |
|---|---:|---|
| Audio callback / CoreAudio block | 128 frames | realtime safe only |
| Status JSON | 20–60 Hz | lightweight snapshot writer |
| ESP32 serial decisions | 20–50 Hz | bounded relative commands |
| Camera preview/tracking | 1–4 Hz | person/scene features |
| Reflective review | 2–10 min | agent or deterministic summarizer |
| Human/operator review | before show + after show | notes, patch changes, repo updates |

## Heuristic review prompts

If an agent is used, give it only bounded telemetry summaries and the current allowed schema. Do not give it direct hardware tools.

Useful questions:

- Has the system been too static, too busy, or well-balanced?
- Are glitches firing with perceptual evidence, or false-triggering from drone derivative artifacts?
- Is the room still but the patch continues to wobble?
- Are lights spending enough time in black/off range?
- Are visitors finding a perceivable connection between movement and sound/light?
- Did any watchdogs, stale frames, zero audio, or command-rate limits trip?
- Which small profile adjustment should be tried for the next window?

The answer should be a JSON profile plus a short reason, not free-form live instructions.

## Max/MSP / DAW bridge compatibility

If Lisbon moves part of the realtime layer to Max/MSP, SuperCollider, a DAW, or a dedicated CoreAudio bridge, keep the same split:

```text
Max/MSP / realtime bridge
  - audio routing
  - signal analysis
  - deterministic response
  - OSC/UDP/WebSocket/JSON profile input

Reflective sidecar
  - reviews logs/status
  - writes heuristic profile
  - never blocks audio
```

Max is an excellent realtime performer. The agent is a composer/dramaturg/systems tuner that changes the envelope of behavior over minutes.

## Safety and rollback

- Keep a known-good default profile in code or docs.
- Write profile files atomically: temp file then rename.
- Include `expires_at`; stale profiles self-disable.
- Log `profile_id` and `reason` into status/log tail.
- Maintain a human kill switch: `/api/silence`, physical mixer mute, and hardware bypass.
- If a profile makes the work worse, delete/disable the file and fall back to local defaults.

## First implementation target

Do not start by adding live LLM calls. Start with a deterministic reviewer script that summarizes the last few minutes of `swn_camera_soundscape_status.json` snapshots, chooses one of a few hand-authored profiles, and writes `heuristic_profile.json`.

Only after that feels useful should an agent be allowed to propose profile changes — still within the same bounded schema and with the same fast-loop clamps.
