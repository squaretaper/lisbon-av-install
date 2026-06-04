#!/usr/bin/env python3
"""Sync the ESP32 red lights to the Lisbon SWN soundscape status JSON.

This intentionally drives the firmware's existing one-character serial protocol:
0/1/2/3/4/x/a plus +/- brightness. The mapping is pure-red at the firmware layer;
this script only selects red motion modes and brightness from audio frequency/glitch
telemetry plus the human scene fallback.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
import termios
import time
import tty
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable


BAUD_BY_RATE = {
    9600: termios.B9600,
    19200: termios.B19200,
    38400: termios.B38400,
    57600: termios.B57600,
    115200: termios.B115200,
}


@dataclass(frozen=True)
class LightState:
    mode: str
    brightness: int
    reason: str
    chase_ms: int | None = None
    pulse_depth: int | None = None
    packet_span: int | None = None


def _clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, float(value)))


def _num(mapping: dict[str, Any], key: str, default: float = 0.0) -> float:
    try:
        return float(mapping.get(key, default))
    except (TypeError, ValueError):
        return default


def _drone_motion_params(freq_hz: float, energy: float, low_band: float) -> tuple[int, int, int]:
    freq = _clamp(freq_hz if freq_hz > 0 else 90.0, 55.0, 950.0)
    norm = _clamp(math.log2(freq / 55.0) / math.log2(950.0 / 55.0), 0.0, 1.0)
    motion_norm = norm ** 1.8
    chase_ms = int(round(_clamp(168.0 - 128.0 * motion_norm, 40.0, 168.0) / 4.0) * 4)
    pulse_depth = int(round(_clamp(44.0 + 36.0 * energy + 16.0 * low_band, 48.0, 96.0) / 8.0) * 8)
    packet_span = int(round(_clamp(10.0 + 28.0 * (1.0 - motion_norm) + 8.0 * low_band, 10.0, 44.0) / 2.0) * 2)
    return chase_ms, pulse_depth, packet_span


def _chord_pulse_period_ms(chord: dict[str, Any] | None) -> int | None:
    """Derive a slow pulse period (ms) tightly correlated with the active chord root.

    The musical idea: when the chord settles on a low D2 (root_semitones ~36),
    the LEDs breathe slowly; when the chord climbs to F3 (~53), the breath
    quickens slightly. Stays in a glacial 320-960ms band so it reads as
    breathing, never as flicker. Returns None when no chord block is present
    so the caller can fall back to the existing audio-derived chase_ms.
    """
    if not isinstance(chord, dict):
        return None
    root = chord.get("root_semitones")
    if not isinstance(root, (int, float)):
        return None
    # Map root semitone (0..60 = C0..B5) to a pulse band [960ms slow, 320ms fast].
    # Low roots = slow breath, higher roots = slightly faster.
    norm = _clamp((float(root) - 24.0) / 36.0, 0.0, 1.0)  # 24=C2 baseline, 60=B5
    return int(round(960.0 - 640.0 * norm))

def state_from_soundscape_status(status: dict[str, Any]) -> LightState:
    """Map soundscape JSON to one of the ESP32 red-only motion states.

    Real ES-9 input audio is the first choice. If that return is silent, use the
    live SWN CV status as a sonic proxy: Browse plus CV7 movement-gate become
    a frequency-ish chase driver, while Dispersion/Pattern/Depth become a glitch
    driver. People features are only an idle fallback, not the primary lighting association.
    """

    if not status.get("ok", False):
        return LightState(mode="x", brightness=0, reason="status not ok")

    audio = status.get("audio_input") or {}
    scene = status.get("person_scene") or {}
    features = status.get("features") or {}
    cv = status.get("cv") or {}
    chord = status.get("chord") or None  # active chord block, may be None
    chord_pulse_ms = _chord_pulse_period_ms(chord)
    max_cv = max(0.05, _num(status, "max_cv", 0.20))

    rms = max(_num(audio, "stereo_rms"), _num(audio, "input_1_rms"), _num(audio, "input_2_rms"))
    peak = max(_num(audio, "stereo_peak"), _num(audio, "input_1_peak"), _num(audio, "input_2_peak"))
    audio_present = rms > 1e-5 or peak > 1e-5
    dominant_freq = _num(audio, "dominant_frequency_hz")
    zero_freq = max(_num(audio, "freq_hz"), _num(audio, "zero_crossing_hz"))
    freq_hz = dominant_freq if dominant_freq > 0 else zero_freq
    spectral_centroid = _num(audio, "spectral_centroid_hz")
    high_band = _clamp(_num(audio, "high_band_ratio"), 0.0, 1.0)
    mid_band = _clamp(_num(audio, "mid_band_ratio"), 0.0, 1.0)
    low_band = _clamp(_num(audio, "low_band_ratio"), 0.0, 1.0)
    high_freq = _clamp(max(_num(audio, "high_freq_ratio"), _num(audio, "high_frequency_ratio"), high_band), 0.0, 1.0)
    glitch = _clamp(_num(audio, "glitch_score"), 0.0, 1.0)
    transient = _clamp(max(_num(audio, "transient"), _num(audio, "transient_score")), 0.0, 1.0)

    browse = _clamp(_num(cv, "cv4_wavetable_browse") / max_cv, 0.0, 1.0)
    # CV5 was 'dispersion', now 'transpose' (Pablo repatched 6/3). For the
    # ESP32 lighting layer this is just another modulation signal — its
    # role downstream is "another scene-feature CV value to drive light
    # speed/intensity." Read either label so the script keeps working
    # whether the bridge writes the old or new key.
    dispersion = _clamp(
        (_num(cv, "cv5_transpose") if "cv5_transpose" in cv else _num(cv, "cv5_dispersion"))
        / max_cv,
        0.0, 1.0,
    )
    # CV6 is now the main-mix VCA (was cv6_dispersion_pattern). It tracks
    # overall room energy with glacial smoothing — a perfect ENERGY envelope
    # for the slow red breathing layer. Back-compat: read the old label if
    # the snapshot is from a pre-remap deployment.
    main_mix_vca = _clamp(
        (_num(cv, "cv6_main_mix_vca") if "cv6_main_mix_vca" in cv else _num(cv, "cv6_dispersion_pattern"))
        / max_cv,
        0.0,
        1.0,
    )
    # CV7 is now the glitch trigger (was cv7_movement_gate). It opens the
    # O&C logic gate that gates pink noise into SWN dispersion_pattern.
    # Audibly this is the high-frequency glitch spice — use it to fire
    # strobe bursts on the ESP32 layer for tight audio/light correlation.
    glitch_trigger = _clamp(
        (_num(cv, "cv7_glitch_trigger") if "cv7_glitch_trigger" in cv else _num(cv, "cv7_movement_gate"))
        / max_cv,
        0.0,
        1.0,
    )
    # Legacy alias kept so the rest of this function reads naturally.
    movement_gate = glitch_trigger
    pattern = main_mix_vca  # slow energy envelope, was the old "pattern" role
    depth = _clamp(_num(cv, "cv8_depth") / max_cv, 0.0, 1.0)

    # --- C200 mic integration (operator request 6/4) ---
    # The room-audio probe runs on :8767 and writes its own status JSON next to
    # the bridge's. It carries the C200 microphone's live RMS, peak, dom freq,
    # and band ratios — independent of the ES-9 return path (which we don't
    # use at this install; ES-9 outs go DIRECT to monitors). Feeding the mic
    # into the lights gives us a real acoustic envelope for brightness and an
    # independent strobe path that fires on actual room-sound transients
    # (claps, sharp gestures, anyone making noise), separate from the CV7
    # glitch trigger. Both are OR'd into the strobe decision below so either
    # signal can fire mode 2.
    mic = status.get("room_audio") or {}
    mic_rms = _num(mic, "rms")
    mic_peak = _num(mic, "peak")
    mic_dom_hz = _num(mic, "dom_freq_hz")
    mic_high_band = _clamp(_num(mic, "band_high"), 0.0, 1.0)
    mic_mid_band = _clamp(_num(mic, "band_mid"), 0.0, 1.0)
    mic_low_band = _clamp(_num(mic, "band_low"), 0.0, 1.0)
    mic_active = mic_rms > 1e-3 or mic_peak > 5e-3
    # Mic transient: a peak well above the RMS floor is a sharp event (clap,
    # voice burst). Normalize to 0..1 so the strobe path can use it.
    mic_transient = _clamp((mic_peak - mic_rms * 3.0) / 0.25, 0.0, 1.0) if mic_active else 0.0
    # Mic energy: brings room sound into the brightness envelope so anyone
    # talking/clapping audibly brightens the strip. 0.10 RMS = strong.
    mic_energy = _clamp((mic_rms / 0.10) * 0.7 + (mic_peak / 0.40) * 0.3, 0.0, 1.0) if mic_active else 0.0
    # --- end mic integration ---

    soundscape_freq_hz = 120.0 + 3880.0 * _clamp(0.78 * browse + 0.22 * glitch_trigger, 0.0, 1.0)
    soundscape_high = _clamp(0.35 * glitch_trigger + 0.65 * browse, 0.0, 1.0)
    # Glitch score: weighted toward the explicit glitch_trigger CV plus
    # dispersion (the actual pink-noise injection level). Pattern (now
    # main_mix_vca) and depth contribute less because they're slow.
    soundscape_glitch = _clamp(0.55 * glitch_trigger + 0.30 * dispersion + 0.10 * depth + 0.05 * main_mix_vca, 0.0, 1.0)
    soundscape_energy = _clamp(0.32 * browse + 0.18 * glitch_trigger + 0.24 * depth + 0.26 * dispersion, 0.0, 1.0)

    people = int(max(0.0, _num(scene, "people_count")))
    activity = _clamp(_num(scene, "activity"), 0.0, 1.0)
    near = _clamp(_num(scene, "nearest_distance"), 0.0, 1.0)
    spread = _clamp(_num(scene, "spread_x"), 0.0, 1.0)
    visual_motion = _clamp(_num(features, "motion"), 0.0, 1.0)

    # Modular/rack levels are interface-normalized. Treat ~0.18 RMS as strong.
    # When the ES-9 return is silent, keep the LEDs tied to the SWN sound-control
    # vector rather than the camera/person count. C200 mic energy (operator
    # request 6/4) folds in as a third path so the room's actual acoustic
    # volume drives the strip when neither ES-9 return nor soundscape moves.
    audio_energy = _clamp((rms / 0.18) * 0.75 + (peak / 0.55) * 0.25, 0.0, 1.0)
    fallback_energy = _clamp(0.55 * activity + 0.25 * near + 0.20 * visual_motion, 0.0, 1.0)
    if audio_present:
        energy = max(audio_energy, mic_energy * 0.85)
        brightness_glitch = max(glitch, mic_transient)
        brightness_high = max(high_freq, mic_high_band)
    elif mic_active:
        # Mic-only path: room is loud, ES-9 return is quiet (typical for our
        # direct-out install). Drive the strip from the mic + soundscape.
        energy = max(mic_energy, soundscape_energy * 0.6)
        brightness_glitch = max(mic_transient, soundscape_glitch * 0.7)
        brightness_high = max(mic_high_band, soundscape_high * 0.5)
    else:
        energy = max(soundscape_energy, fallback_energy * 0.35)
        brightness_glitch = soundscape_glitch
        brightness_high = soundscape_high

    brightness = int(round(_clamp(16 + 112 * energy + 58 * brightness_glitch + 26 * brightness_high, 0, 192) / 16.0) * 16)
    brightness = int(_clamp(brightness, 0, 176))
    # Strobe decision tree (rebuilt 6/4 for operator request):
    #
    #   PRIORITY 1: CV7 glitch trigger direct fire. The whole point of CV7
    #     is "the audio just glitched out, slam the lights". Below 6/4 we
    #     had a softer threshold (cv7 >= 0.52 gated by audio_present==False)
    #     which never fired during normal performance because the audio
    #     return was always non-zero. Now: ANY cv7 >= 0.40 of max_cv fires
    #     mode 2 with brightness scaled by the trigger magnitude. No other
    #     conditions. The CV is the contract.
    #
    #   PRIORITY 2: Mic transient direct fire. A loud clap, voice burst, or
    #     sharp acoustic event in the room (the C200 mic catches it) fires
    #     strobe even when CV7 is quiet. This couples lights to room sound
    #     independent of the modular patch.
    #
    #   PRIORITY 3 (legacy): the audio-spectrum strobe path. Kept because
    #     it still catches ES-9 return content if/when we ever route it.
    #
    # Strobes always pull at least 192 brightness (was 208) and scale up
    # from there. Operator wants "intense strobing" — brightness ceiling
    # raised to 248 (was 240).
    spectral_brightness = _clamp((spectral_centroid - 550.0) / 1800.0, 0.0, 1.0)
    high_band_burst = high_band >= 0.16 and spectral_centroid >= 900 and low_band <= 0.78
    bright_transient = transient >= 0.32 and low_band <= 0.78 and (
        high_band >= 0.05 or high_freq >= 0.10 or mid_band >= 0.42 or spectral_centroid >= 800 or freq_hz >= 700
    )
    mid_high_glitch = glitch >= 0.20 and low_band <= 0.70 and (
        freq_hz >= 700 or spectral_centroid >= 700 or high_band >= 0.06 or mid_band >= 0.50
    )
    hard_high_frequency = freq_hz >= 1800 and (
        (high_band >= 0.08 and spectral_centroid >= 1000)
        or (high_freq >= 0.35 and (transient >= 0.10 or glitch >= 0.18))
        or spectral_centroid >= 1600
    )
    strobe_score = _clamp(max(
        0.72 * high_band + 0.28 * spectral_brightness,
        (0.58 * transient + 0.24 * high_band + 0.18 * spectral_brightness) if bright_transient else 0.0,
        (0.52 * glitch + 0.30 * mid_band + 0.18 * spectral_brightness) if mid_high_glitch else 0.0,
        (0.50 * high_freq + 0.35 * high_band + 0.15 * spectral_brightness) if hard_high_frequency else 0.0,
    ), 0.0, 1.0)
    strobe_active = high_band_burst or bright_transient or mid_high_glitch or hard_high_frequency

    # PRIORITY 1: CV7 glitch direct strobe
    if glitch_trigger >= 0.40:
        strobe_brightness = int(round(_clamp(208 + 40 * glitch_trigger, 208, 248) / 16.0) * 16)
        return LightState(mode="2", brightness=strobe_brightness, reason=f"cv7 glitch direct strobe {glitch_trigger:.2f}")
    # PRIORITY 2: Mic transient direct strobe
    if mic_active and mic_transient >= 0.45:
        strobe_brightness = int(round(_clamp(208 + 40 * mic_transient + 16 * mic_high_band, 208, 248) / 16.0) * 16)
        return LightState(mode="2", brightness=strobe_brightness, reason=f"mic transient strobe {mic_transient:.2f} peak={mic_peak:.3f}")
    # PRIORITY 3: legacy audio-spectrum strobe (ES-9 return content)
    if audio_present and strobe_active and strobe_score >= 0.16:
        strobe_brightness = int(round(_clamp(192 + 56 * strobe_score + 26 * high_band + 18 * transient, 208, 248) / 16.0) * 16)
        return LightState(mode="2", brightness=strobe_brightness, reason=f"audio glitch strobe {strobe_score:.2f} band={high_band:.2f} centroid={spectral_centroid:.0f}Hz trans={transient:.2f}")
    if (not audio_present) and soundscape_glitch >= 0.52:
        return LightState(mode="2", brightness=max(112, brightness), reason=f"soundscape glitch {soundscape_glitch:.2f}")
    if audio_present and (freq_hz >= 1400 or high_freq >= 0.28):
        return LightState(mode="1", brightness=max(96, brightness), reason=f"audio high freq chase {freq_hz:.0f}Hz high={high_freq:.2f}")
    if audio_present:
        if audio_energy < 0.04:
            chase_ms, pulse_depth, packet_span = _drone_motion_params(freq_hz, audio_energy, low_band)
            # Blend chord-correlated pulse rate when available. Chord pulse
            # is the slow musical clock (root_semitones-derived); audio chase
            # is the fast-loop reaction. 70/30 chord-dominant in faint drones
            # so the visual stays locked to the chord even when audio is
            # marginal.
            if chord_pulse_ms is not None:
                chase_ms = int(round(0.7 * chord_pulse_ms + 0.3 * chase_ms))
            faint_brightness = int(round(_clamp(24 + 72 * audio_energy + 16 * low_band, 16, 64) / 16.0) * 16)
            return LightState(
                mode="1",
                brightness=faint_brightness,
                chase_ms=chase_ms,
                pulse_depth=pulse_depth,
                packet_span=packet_span,
                reason=f"audio faint drone chase {freq_hz:.0f}Hz speed={chase_ms}ms span={packet_span}" + (f" chord_pulse={chord_pulse_ms}ms" if chord_pulse_ms else ""),
            )
        chase_ms, pulse_depth, packet_span = _drone_motion_params(freq_hz, audio_energy, low_band)
        # Same chord-pulse blend, weighted slightly less (50/50) when audio
        # is energetic — the room is loud, the chord still matters but the
        # spectral content should drive faster motion.
        if chord_pulse_ms is not None:
            chase_ms = int(round(0.5 * chord_pulse_ms + 0.5 * chase_ms))
        drone_brightness = int(round(_clamp(24 + 128 * (audio_energy ** 0.85) + 28 * low_band, 16, 176) / 16.0) * 16)
        return LightState(
            mode="1",
            brightness=drone_brightness,
            chase_ms=chase_ms,
            pulse_depth=pulse_depth,
            packet_span=packet_span,
            reason=f"audio drone chase {freq_hz:.0f}Hz speed={chase_ms}ms pulse={pulse_depth} span={packet_span} energy={audio_energy:.2f}" + (f" chord_pulse={chord_pulse_ms}ms" if chord_pulse_ms else ""),
        )
    if (not audio_present) and (soundscape_freq_hz >= 1400 or soundscape_high >= 0.45):
        return LightState(mode="1", brightness=max(80, brightness), reason=f"soundscape freq {soundscape_freq_hz:.0f}Hz high={soundscape_high:.2f}")
    if people >= 2 or spread >= 0.34:
        return LightState(mode="3", brightness=max(80, brightness), reason=f"group/spread idle people={people} spread={spread:.2f}")
    if people == 1 and near >= 0.58:
        return LightState(mode="1", brightness=max(80, brightness), reason=f"near person idle {near:.2f}")
    return LightState(mode="4", brightness=max(32, min(brightness, 80)), reason="empty/low-frequency red breath")


def commands_for_transition(
    current: LightState | None,
    target: LightState,
    *,
    brightness_step: int = 16,
    max_brightness_steps: int = 3,
    chase_step_ms: int = 4,
    pulse_step: int = 8,
    packet_span_step: int = 2,
    max_param_steps: int = 2,
) -> list[str]:
    """Return dual-strip firmware commands needed to approach target."""

    commands: list[str] = []
    if current is None or current.mode != target.mode:
        commands.append(target.mode)

    if current is None:
        current_brightness = 64
        current_chase_ms = 96
        current_pulse_depth = 42
        current_packet_span = 20
    else:
        current_brightness = current.brightness
        current_chase_ms = current.chase_ms if current.chase_ms is not None else 96
        current_pulse_depth = current.pulse_depth if current.pulse_depth is not None else 42
        current_packet_span = current.packet_span if current.packet_span is not None else 20

    delta = int(round((target.brightness - current_brightness) / max(1, brightness_step)))
    delta = int(_clamp(delta, -max_brightness_steps, max_brightness_steps))
    if delta > 0:
        commands.extend(["+"] * delta)
    elif delta < 0:
        commands.extend(["-"] * abs(delta))

    if target.chase_ms is not None:
        speed_delta = int(round((current_chase_ms - target.chase_ms) / max(1, chase_step_ms)))
        speed_delta = int(_clamp(speed_delta, -max_param_steps, max_param_steps))
        if speed_delta > 0:
            commands.extend([">"] * speed_delta)
        elif speed_delta < 0:
            commands.extend(["<"] * abs(speed_delta))

    if target.pulse_depth is not None:
        pulse_delta = int(round((target.pulse_depth - current_pulse_depth) / max(1, pulse_step)))
        pulse_delta = int(_clamp(pulse_delta, -max_param_steps, max_param_steps))
        if pulse_delta > 0:
            commands.extend(["]"] * pulse_delta)
        elif pulse_delta < 0:
            commands.extend(["["] * abs(pulse_delta))
    if target.packet_span is not None:
        span_delta = int(round((target.packet_span - current_packet_span) / max(1, packet_span_step)))
        span_delta = int(_clamp(span_delta, -max_param_steps, max_param_steps))
        if span_delta > 0:
            commands.extend(["}"] * span_delta)
        elif span_delta < 0:
            commands.extend(["{"] * abs(span_delta))
    return commands


def state_after_commands(current: LightState | None, commands: Iterable[str], target: LightState) -> LightState:
    """Track the hardware state reached after bounded one-character commands."""

    mode = current.mode if current is not None else target.mode
    brightness = current.brightness if current is not None else 64
    chase_ms = current.chase_ms if current is not None and current.chase_ms is not None else 96
    pulse_depth = current.pulse_depth if current is not None and current.pulse_depth is not None else 42
    packet_span = current.packet_span if current is not None and current.packet_span is not None else 20
    for command in commands:
        if command in {"0", "1", "2", "3", "4", "x"}:
            mode = command
        elif command == "+":
            brightness = int(_clamp(brightness + 16, 0, 255))
        elif command == "-":
            brightness = int(_clamp(brightness - 16, 0, 255))
        elif command == ">":
            chase_ms = int(_clamp(chase_ms - 4, 18, 168))
        elif command == "<":
            chase_ms = int(_clamp(chase_ms + 4, 18, 168))
        elif command == "]":
            pulse_depth = int(_clamp(pulse_depth + 8, 8, 112))
        elif command == "[":
            pulse_depth = int(_clamp(pulse_depth - 8, 8, 112))
        elif command == "}":
            packet_span = int(_clamp(packet_span + 2, 8, 44))
        elif command == "{":
            packet_span = int(_clamp(packet_span - 2, 8, 44))
    if target.chase_ms is None:
        chase_ms = current.chase_ms if current is not None else None
    if target.pulse_depth is None:
        pulse_depth = current.pulse_depth if current is not None else None
    if target.packet_span is None:
        packet_span = current.packet_span if current is not None else None
    return LightState(mode=mode, brightness=brightness, chase_ms=chase_ms, pulse_depth=pulse_depth, packet_span=packet_span, reason=target.reason)


class SerialWriter:
    def __init__(self, device: str, *, baud: int = 115200) -> None:
        self.device = device
        self.baud = baud
        self.fd: int | None = None
        self._old_attrs: list[Any] | None = None

    def __enter__(self) -> "SerialWriter":
        self.fd = os.open(self.device, os.O_RDWR | os.O_NOCTTY | os.O_NONBLOCK)
        self._old_attrs = termios.tcgetattr(self.fd)
        tty.setraw(self.fd)
        attrs = termios.tcgetattr(self.fd)
        baud_const = BAUD_BY_RATE.get(self.baud, termios.B115200)
        attrs[4] = baud_const
        attrs[5] = baud_const
        attrs[2] |= termios.CLOCAL | termios.CREAD
        termios.tcsetattr(self.fd, termios.TCSANOW, attrs)
        time.sleep(0.2)
        return self

    def __exit__(self, _exc_type, _exc, _tb) -> None:
        if self.fd is not None:
            if self._old_attrs is not None:
                termios.tcsetattr(self.fd, termios.TCSANOW, self._old_attrs)
            os.close(self.fd)
            self.fd = None

    def write_commands(self, commands: Iterable[str], *, delay: float = 0.035) -> None:
        if self.fd is None:
            raise RuntimeError("serial port is not open")
        for command in commands:
            os.write(self.fd, command.encode("ascii"))
            time.sleep(delay)


def read_status(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text())


def merge_mic_into_status(status: dict[str, Any], mic_path: Path | None) -> dict[str, Any]:
    """Optionally fold the C200 mic probe status into the soundscape status dict.

    The bridge writes swn_camera_soundscape_status.json. The room-audio probe
    writes room_audio_probe_status.json. We don't change either producer; we
    just merge the mic snapshot under the 'room_audio' key when both exist so
    state_from_soundscape_status() can read it through the same status dict.
    Silently no-op when the mic file is missing or unreadable so the sync
    keeps working if the audio probe is restarting.
    """
    if mic_path is None:
        return status
    try:
        mic = json.loads(mic_path.read_text())
    except (OSError, json.JSONDecodeError):
        return status
    if isinstance(mic, dict) and mic.get("ok"):
        status["room_audio"] = mic
    return status


def status_age_ms(status: dict[str, Any], *, observed_at: float | None = None) -> int | None:
    timestamp = status.get("timestamp")
    if not isinstance(timestamp, (int, float)):
        return None
    now = time.time() if observed_at is None else observed_at
    return max(0, int(round((now - float(timestamp)) * 1000.0)))


def run_sync(args: argparse.Namespace) -> int:
    status_path = Path(args.status_path)
    mic_path = Path(args.mic_status_path) if args.mic_status_path else None
    current = LightState(
        mode=args.initial_mode,
        brightness=args.initial_brightness,
        chase_ms=args.initial_chase_ms,
        pulse_depth=args.initial_pulse_depth,
        packet_span=args.initial_packet_span,
        reason="initial",
    )
    last_mtime = 0.0

    writer_context = None if args.dry_run else SerialWriter(args.serial, baud=args.baud)
    writer = writer_context.__enter__() if writer_context is not None else None
    try:
        start = time.monotonic()
        while args.duration <= 0 or time.monotonic() - start < args.duration:
            try:
                stat = status_path.stat()
                if stat.st_mtime != last_mtime:
                    last_mtime = stat.st_mtime
                    status = read_status(status_path)
                    status = merge_mic_into_status(status, mic_path)
                    observed_at = time.time()
                    age = status_age_ms(status, observed_at=observed_at)
                    age_suffix = f" age={age}ms" if age is not None else ""
                    target = state_from_soundscape_status(status)
                    commands = commands_for_transition(
                        current,
                        target,
                        max_brightness_steps=args.max_brightness_steps,
                        max_param_steps=args.max_param_steps,
                    )
                    if commands:
                        print(f"{time.strftime('%H:%M:%S')} {' '.join(commands)} -> {target.mode}/{target.brightness}: {target.reason}{age_suffix}", flush=True)
                        if writer is not None:
                            writer.write_commands(commands, delay=args.serial_delay)
                        current = state_after_commands(current, commands, target)
                    else:
                        current = target
            except FileNotFoundError:
                print(f"waiting for {status_path}", file=sys.stderr, flush=True)
            except json.JSONDecodeError as exc:
                print(f"status JSON not ready: {exc}", file=sys.stderr, flush=True)
            time.sleep(args.interval)
    finally:
        if writer_context is not None:
            writer_context.__exit__(None, None, None)
    return 0


def build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Sync ESP32 pure-red lights to Lisbon soundscape audio frequency/glitches.")
    p.add_argument("--status-path", default="audio/runtime/swn_camera_soundscape_status.json")
    p.add_argument(
        "--mic-status-path",
        default="audio/runtime/room_audio_probe_status.json",
        help="path to the C200 mic probe status JSON; pass empty string to disable mic integration",
    )
    p.add_argument("--serial", default="/dev/cu.usbserial-0001")
    p.add_argument("--baud", type=int, default=115200)
    p.add_argument("--interval", type=float, default=0.02)
    p.add_argument("--duration", type=float, default=0.0, help="seconds to run; 0 means forever")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--initial-mode", default="4")
    p.add_argument("--initial-brightness", type=int, default=64)
    p.add_argument("--initial-chase-ms", type=int, default=96)
    p.add_argument("--initial-pulse-depth", type=int, default=42)
    p.add_argument("--initial-packet-span", type=int, default=20)
    p.add_argument("--max-brightness-steps", type=int, default=6)
    p.add_argument("--max-param-steps", type=int, default=6)
    p.add_argument("--serial-delay", type=float, default=0.001)
    return p


def main(argv: list[str] | None = None) -> int:
    return run_sync(build_arg_parser().parse_args(argv))


if __name__ == "__main__":
    raise SystemExit(main())
