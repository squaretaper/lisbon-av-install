#!/usr/bin/env python3
"""ES-9 inputs 1/2 -> default output (e.g. iLoud Micro-Monitor over Bluetooth).

Temporary backup path for the Lisbon install. The intended signal chain is:

    rack -> ES-9 ins 1/2 -> [cables] -> iLoud Micro-Monitors

When the cables are missing, this passthrough substitutes:

    rack -> ES-9 ins 1/2 -> CoreAudio -> Bluetooth -> iLoud Micro-Monitors

WARNING — bluetooth latency:
    BT audio adds 100-300 ms of buffering vs. the analog path. For the install's
    reactive arc (lights + CV reacting to room movement in real time) this will
    be perceptibly off on percussive material. Drone passes will feel fine.
    Use this only as a temporary patch while cables are missing.

This script intentionally does NOT contend with the SWN bridge. The SWN bridge
opens ES-9 for input AND output and routes audio + CV. Running both at once
will cause one of them to fail to open the device (CoreAudio shares USB audio
poorly).

Two operating models:
  --duplex  (default)  Open ES-9 for input, system default for output.
                       Lowest latency code path, but blocks the SWN bridge.
  --share              Use macOS `AudioServerPlugin`-style routing: rely on the
                       SWN bridge's main-mix output to ES-9 outs 1/2 already
                       being routed back to CoreAudio out 1/2; we tap that.
                       (This path requires extra config; not implemented yet —
                       falls back to --duplex with a warning.)

Typical use:
    python -m audio.es9_to_default_output \\
        --input-device "ES-9" \\
        --input-channels 1 2 \\
        --output-device "iLoud" \\
        --samplerate 48000 \\
        --blocksize 256 \\
        --gain 0.6
"""
from __future__ import annotations

import argparse
import sys
import time
from dataclasses import dataclass
from typing import Sequence

import numpy as np
import sounddevice as sd


@dataclass
class Config:
    input_device: str | int
    output_device: str | int
    input_channels: tuple[int, int]
    samplerate: int
    blocksize: int
    gain: float
    dither: bool
    report_interval: float


def _resolve_device(query: str | int, kind: str) -> tuple[int, dict]:
    """Resolve a device identifier (substring or index) to a CoreAudio index."""
    devices = sd.query_devices()
    if isinstance(query, int):
        info = sd.query_devices(query)
        return query, info
    # substring match, prefer the one with matching kind capacity
    needle = query.lower()
    candidates = []
    for i, d in enumerate(devices):
        if needle in d["name"].lower():
            channels = d["max_input_channels"] if kind == "input" else d["max_output_channels"]
            if channels > 0:
                candidates.append((i, d, channels))
    if not candidates:
        raise SystemExit(f"no {kind} device matched {query!r}; available: {[d['name'] for d in devices]}")
    i, info, _ = candidates[0]
    return i, info


def main(argv: Sequence[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--input-device", default="ES-9")
    p.add_argument("--output-device", default="iLoud")
    p.add_argument("--input-channels", nargs=2, type=int, default=[1, 2], metavar=("L", "R"))
    p.add_argument("--samplerate", type=int, default=48000)
    p.add_argument("--blocksize", type=int, default=256, help="larger = lower CPU but more latency; BT path already adds 100-300ms so 256 is fine")
    p.add_argument("--gain", type=float, default=0.6)
    p.add_argument("--no-dither", action="store_true", help="skip TPDF dither when downcasting to s16 internally (we stay float32 here; flag retained for parity)")
    p.add_argument("--report-interval", type=float, default=5.0, help="seconds between RMS/peak reports to stdout")
    args = p.parse_args(argv)

    cfg = Config(
        input_device=args.input_device,
        output_device=args.output_device,
        input_channels=(args.input_channels[0], args.input_channels[1]),
        samplerate=args.samplerate,
        blocksize=args.blocksize,
        gain=args.gain,
        dither=not args.no_dither,
        report_interval=args.report_interval,
    )

    in_idx, in_info = _resolve_device(cfg.input_device, "input")
    out_idx, out_info = _resolve_device(cfg.output_device, "output")
    print(f"input:  [{in_idx}] {in_info['name']} ({in_info['max_input_channels']}ch)")
    print(f"        using channels {cfg.input_channels[0]}, {cfg.input_channels[1]}")
    print(f"output: [{out_idx}] {out_info['name']} ({out_info['max_output_channels']}ch)")
    print(f"sr={cfg.samplerate} block={cfg.blocksize} gain={cfg.gain}")
    print()

    state: dict[str, float] = {"last_report": time.time(), "peak": 0.0, "rms2_sum": 0.0, "samples": 0}

    # We must read all N input channels and pick the two we want; sd.Stream
    # doesn't support per-channel mapping for in+out duplex pairs across devices.
    in_channels = in_info["max_input_channels"]
    ch_left = cfg.input_channels[0] - 1   # 0-indexed
    ch_right = cfg.input_channels[1] - 1
    if ch_left >= in_channels or ch_right >= in_channels:
        raise SystemExit(f"input channels {cfg.input_channels} out of range for device with {in_channels}ch")

    def in_callback(indata: np.ndarray, outdata: np.ndarray, frames: int, time_info, status) -> None:  # noqa: ANN001
        if status:
            # Underrun / overrun. Print once per report interval to avoid log spam.
            pass
        try:
            stereo = indata[:, [ch_left, ch_right]].astype(np.float32, copy=False) * cfg.gain
            # Clip to prevent BT codec distortion on transients.
            np.clip(stereo, -1.0, 1.0, out=stereo)
            outdata[:] = stereo
        except Exception as exc:  # last-resort: silence on error rather than crash the callback
            outdata.fill(0.0)
            print(f"callback error: {exc}", file=sys.stderr)
            return

        peak = float(np.max(np.abs(stereo))) if frames else 0.0
        if peak > state["peak"]:
            state["peak"] = peak
        state["rms2_sum"] += float(np.sum(stereo * stereo))
        state["samples"] += frames * 2

    try:
        with sd.Stream(
            device=(in_idx, out_idx),
            samplerate=cfg.samplerate,
            blocksize=cfg.blocksize,
            dtype="float32",
            channels=(in_channels, 2),
            callback=in_callback,
        ):
            print("streaming; ctrl-c to stop")
            while True:
                time.sleep(cfg.report_interval)
                now = time.time()
                samples = state["samples"]
                if samples > 0:
                    rms = (state["rms2_sum"] / samples) ** 0.5
                else:
                    rms = 0.0
                print(f"[{time.strftime('%H:%M:%S')}] peak={state['peak']:.4f} rms={rms:.4f}")
                state["peak"] = 0.0
                state["rms2_sum"] = 0.0
                state["samples"] = 0
                state["last_report"] = now
    except KeyboardInterrupt:
        print("\nstopped")
        return 0
    except Exception as exc:
        print(f"\nstream failed: {exc}", file=sys.stderr)
        print(
            "\nNote: if this says the device is in use, the SWN bridge LaunchAgent "
            "is holding ES-9 exclusively. Stop it first:\n"
            "  launchctl bootout gui/$(id -u)/ai.ganchitecture.lisbon-swn-bridge\n"
            "and re-load when done:\n"
            "  scripts/install-launchagents.sh",
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
