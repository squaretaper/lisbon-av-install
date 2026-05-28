#!/usr/bin/env python3
"""Black-box smoke test for the Lisbon camera bridge HTTP/MJPEG surface.

Runs the app in mock-frame mode so CI/local tests do not need camera permission.
"""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
APP_BIN = ROOT / "cv" / "camera_probe" / "LisbonCameraProbe.app" / "Contents" / "MacOS" / "LisbonCameraProbe"
PORT = 18765
BASE = f"http://127.0.0.1:{PORT}"


def fetch(path: str, timeout: float = 2.0) -> tuple[bytes, dict[str, str]]:
    with urllib.request.urlopen(f"{BASE}{path}", timeout=timeout) as response:
        headers = {k.lower(): v for k, v in response.headers.items()}
        return response.read(), headers


def wait_for_server(timeout: float = 5.0) -> None:
    deadline = time.time() + timeout
    last_error: Exception | None = None
    while time.time() < deadline:
        try:
            body, _ = fetch("/status", timeout=0.5)
            payload = json.loads(body.decode("utf-8"))
            if payload.get("ok") is True and payload.get("frameCount", 0) > 0:
                return
        except (OSError, urllib.error.URLError, json.JSONDecodeError) as exc:
            last_error = exc
        time.sleep(0.1)
    raise AssertionError(f"camera bridge did not become healthy: {last_error!r}")


def main() -> None:
    assert APP_BIN.exists(), f"missing app binary: {APP_BIN}"
    with tempfile.TemporaryDirectory() as tmp:
        snapshot = Path(tmp) / "latest.jpg"
        proc = subprocess.Popen(
            [
                str(APP_BIN),
                "--mock",
                "--port",
                str(PORT),
                "--snapshot-path",
                str(snapshot),
                "--snapshot-interval",
                "0.25",
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        try:
            wait_for_server()

            status_body, status_headers = fetch("/status")
            assert status_headers.get("content-type", "").startswith("application/json")
            status = json.loads(status_body.decode("utf-8"))
            assert status["ok"] is True
            assert status["mode"] == "mock"
            assert status["frameCount"] > 0
            assert status["latestFrameAgeMs"] < 1500

            frame_body, frame_headers = fetch("/frame.jpg")
            assert frame_headers.get("content-type", "").startswith("image/jpeg")
            assert frame_body.startswith(b"\xff\xd8\xff")
            assert len(frame_body) > 1000

            deadline = time.time() + 2.0
            while time.time() < deadline and not snapshot.exists():
                time.sleep(0.05)
            assert snapshot.exists(), f"snapshot was not written: {snapshot}"
            assert snapshot.read_bytes().startswith(b"\xff\xd8\xff")

            request = urllib.request.Request(f"{BASE}/stream.mjpeg")
            with urllib.request.urlopen(request, timeout=2.0) as response:
                assert response.headers.get("Content-Type", "").startswith("multipart/x-mixed-replace")
                chunk = response.read(4096)
                assert b"--lisbonframe" in chunk
                assert b"Content-Type: image/jpeg" in chunk
                assert b"\xff\xd8\xff" in chunk

            print("camera bridge mock HTTP/MJPEG smoke test passed")
        finally:
            if proc.poll() is None:
                proc.terminate()
            try:
                stdout, stderr = proc.communicate(timeout=2)
            except subprocess.TimeoutExpired:
                proc.kill()
                stdout, stderr = proc.communicate(timeout=2)
            if proc.returncode not in (0, -15, -9):
                raise AssertionError(
                    f"bridge exited unexpectedly with {proc.returncode}\nSTDOUT:\n{stdout}\nSTDERR:\n{stderr}"
                )


if __name__ == "__main__":
    main()
