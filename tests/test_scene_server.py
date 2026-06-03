"""Tests for the SceneServer HTTP preview server.

Verifies routes serve correctly and the file-on-disk pattern works:
the server is just a thin readback layer over the bridge's atomic-write JPG.
"""
from __future__ import annotations

import socket
import time
import urllib.error
import urllib.request
from io import BytesIO
from pathlib import Path

from PIL import Image
import pytest

from audio.lisbon_swn_camera_bridge import SceneServer


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _write_jpg(path: Path, color=(40, 40, 40)) -> bytes:
    img = Image.new("RGB", (64, 48), color)
    buf = BytesIO()
    img.save(buf, format="JPEG", quality=80)
    data = buf.getvalue()
    path.write_bytes(data)
    return data


def test_scene_server_serves_jpg(tmp_path):
    preview = tmp_path / "preview.jpg"
    expected = _write_jpg(preview, color=(80, 0, 0))
    port = _free_port()
    server = SceneServer(port=port, preview_path=preview, host="127.0.0.1")
    server.start()
    try:
        time.sleep(0.05)
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/scene.jpg", timeout=2.0) as r:
            assert r.status == 200
            assert r.headers["Content-Type"] == "image/jpeg"
            body = r.read()
            assert body == expected
    finally:
        server.stop()


def test_scene_server_serves_html_index(tmp_path):
    preview = tmp_path / "preview.jpg"
    _write_jpg(preview)
    port = _free_port()
    server = SceneServer(port=port, preview_path=preview, host="127.0.0.1")
    server.start()
    try:
        time.sleep(0.05)
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=2.0) as r:
            assert r.status == 200
            assert r.headers["Content-Type"].startswith("text/html")
            body = r.read().decode("utf-8")
            assert "scene.jpg" in body
            assert "scene" in body.lower()
    finally:
        server.stop()


def test_scene_server_503_when_no_file(tmp_path):
    preview = tmp_path / "missing.jpg"
    port = _free_port()
    server = SceneServer(port=port, preview_path=preview, host="127.0.0.1")
    server.start()
    try:
        time.sleep(0.05)
        with pytest.raises(urllib.error.HTTPError) as exc_info:
            urllib.request.urlopen(f"http://127.0.0.1:{port}/scene.jpg", timeout=2.0)
        assert exc_info.value.code == 503
    finally:
        server.stop()


def test_scene_server_returns_latest_file_on_each_request(tmp_path):
    """The server reads the file on each GET so the bridge's atomic-write
    pattern is the single source of truth — no caching."""
    preview = tmp_path / "preview.jpg"
    first = _write_jpg(preview, color=(30, 30, 30))
    port = _free_port()
    server = SceneServer(port=port, preview_path=preview, host="127.0.0.1")
    server.start()
    try:
        time.sleep(0.05)
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/scene.jpg", timeout=2.0) as r:
            assert r.read() == first
        # Rewrite with a different color
        second = _write_jpg(preview, color=(220, 0, 0))
        assert second != first
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/scene.jpg", timeout=2.0) as r:
            assert r.read() == second
    finally:
        server.stop()


def test_scene_server_404_for_unknown_path(tmp_path):
    preview = tmp_path / "preview.jpg"
    _write_jpg(preview)
    port = _free_port()
    server = SceneServer(port=port, preview_path=preview, host="127.0.0.1")
    server.start()
    try:
        time.sleep(0.05)
        with pytest.raises(urllib.error.HTTPError) as exc_info:
            urllib.request.urlopen(f"http://127.0.0.1:{port}/nope", timeout=2.0)
        assert exc_info.value.code == 404
    finally:
        server.stop()
