"""scripts/tune.py — writes/reads an isolated tune.json (6/4 r16).

Prior versions merged tune values into heuristic_profile.json, which
the realtime chord driver also rewrote every 750ms. That created a
read-modify-write race where the driver's stale snapshot could
silently clobber a tune.py update. The isolation fix gives tune.py
sole ownership of audio/runtime/tune.json so no other writer can
overwrite it.
"""
from __future__ import annotations

import json
import os
import runpy
import sys
from pathlib import Path

import pytest


@pytest.fixture
def tune_module(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Import scripts/tune.py with TUNE_PATH and LEGACY_PROFILE_PATH
    redirected to a temp dir so tests don't touch the live runtime.
    """
    import importlib.util

    repo_root = Path(__file__).resolve().parent.parent
    tune_src = repo_root / "scripts" / "tune.py"
    spec = importlib.util.spec_from_file_location("tune_test_module", tune_src)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    monkeypatch.setattr(module, "TUNE_PATH", tmp_path / "tune.json")
    monkeypatch.setattr(module, "LEGACY_PROFILE_PATH", tmp_path / "heuristic_profile.json")
    return module


def test_apply_creates_tune_json_with_only_the_provided_keys(tune_module, capsys):
    tune_module.apply(["glitch_fire_threshold=0.018", "cv7_release_ms=175"])
    written = json.loads(tune_module.TUNE_PATH.read_text())
    assert written == {"glitch_fire_threshold": 0.018, "cv7_release_ms": 175.0}


def test_apply_merges_into_existing_tune_file_without_dropping_other_keys(tune_module):
    tune_module.TUNE_PATH.write_text(json.dumps({"browse_rate_min_hz": 0.009}))
    tune_module.apply(["glitch_fire_threshold=0.02"])
    merged = json.loads(tune_module.TUNE_PATH.read_text())
    assert merged == {"browse_rate_min_hz": 0.009, "glitch_fire_threshold": 0.02}


def test_unknown_key_rejected_before_any_write(tune_module):
    with pytest.raises(SystemExit):
        tune_module.apply(["wat_is_this=42"])
    assert not tune_module.TUNE_PATH.exists()


def test_clear_truncates_tune_file_to_empty_dict(tune_module):
    tune_module.TUNE_PATH.write_text(json.dumps({"glitch_fire_threshold": 0.02}))
    tune_module.clear()
    assert json.loads(tune_module.TUNE_PATH.read_text()) == {}


def test_legacy_tune_block_migrated_out_of_profile_on_first_apply(tune_module):
    """Operators upgrading from r13–r15 may still have a `tune` block
    inside heuristic_profile.json. First apply call should strip it
    so the bridge doesn't end up with two competing tune sources.
    """
    legacy = {
        "chord": {"voicing": "minor_triad", "root_semitones": 36},
        "tune": {"glitch_fire_threshold": 0.99},  # stale
    }
    tune_module.LEGACY_PROFILE_PATH.write_text(json.dumps(legacy))
    tune_module.apply(["glitch_fire_threshold=0.018"])
    profile_after = json.loads(tune_module.LEGACY_PROFILE_PATH.read_text())
    assert "tune" not in profile_after
    assert profile_after["chord"] == legacy["chord"]
    assert json.loads(tune_module.TUNE_PATH.read_text()) == {"glitch_fire_threshold": 0.018}


def test_tune_file_is_independent_of_heuristic_profile(tune_module):
    """Smoke-test the isolation: writing tune.json must never touch
    heuristic_profile.json (apart from the one-shot legacy migration
    covered above).
    """
    tune_module.LEGACY_PROFILE_PATH.write_text(json.dumps({"chord": {"voicing": "quartal"}}))
    legacy_mtime_before = tune_module.LEGACY_PROFILE_PATH.stat().st_mtime
    # First apply will run the migration once but the legacy file has no
    # tune block so it should not be rewritten.
    tune_module.apply(["browse_rate_min_hz=0.009"])
    assert tune_module.LEGACY_PROFILE_PATH.stat().st_mtime == legacy_mtime_before
    # Second apply must definitely not touch the legacy file.
    tune_module.apply(["browse_rate_max_hz=0.05"])
    assert tune_module.LEGACY_PROFILE_PATH.stat().st_mtime == legacy_mtime_before
