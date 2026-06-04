"""White-bloom proximity layer (6/4 r25).

Pure-white blend added on top of chase/glitch patterns. Driver = scene
nearest_distance, inverted and square-curved so the bloom builds gently
then commits. Cap at 127 (~50% of full white).
"""
from __future__ import annotations

from lighting.lisbon_esp32_soundscape_sync import (
    LightState,
    commands_for_transition,
    state_after_commands,
)


def test_commands_includes_white_command_when_value_changes():
    current = LightState(mode="1", brightness=128, white_amount=0, reason="current")
    target = LightState(mode="1", brightness=128, white_amount=64, reason="target")
    cmds = commands_for_transition(current, target)
    assert any(c.startswith("w") and c.endswith(";") for c in cmds)
    # The exact command should be "w64;"
    assert "w64;" in cmds


def test_commands_omits_white_when_value_unchanged():
    current = LightState(mode="1", brightness=128, white_amount=64, reason="current")
    target = LightState(mode="1", brightness=128, white_amount=64, reason="target")
    cmds = commands_for_transition(current, target)
    assert not any(c.startswith("w") for c in cmds)


def test_commands_clamps_white_to_127():
    current = LightState(mode="1", brightness=128, white_amount=0, reason="current")
    target = LightState(mode="1", brightness=128, white_amount=200, reason="target")
    cmds = commands_for_transition(current, target)
    assert "w127;" in cmds


def test_state_after_commands_tracks_white():
    current = LightState(mode="1", brightness=128, white_amount=0, reason="current")
    target = LightState(mode="1", brightness=128, white_amount=42, reason="target")
    cmds = commands_for_transition(current, target)
    result = state_after_commands(current, cmds, target)
    assert result.white_amount == 42


def test_state_after_commands_silent_on_no_white_command():
    """If no `w...;` issued, state preserves previous white."""
    current = LightState(mode="1", brightness=128, white_amount=80, reason="current")
    # No target white change
    result = state_after_commands(current, ["+", "-"], current)
    assert result.white_amount == 80


def test_white_command_format_strict():
    """Multi-char command must be 'w' + digits + ';'."""
    current = LightState(mode="2", brightness=255, white_amount=0, reason="current")
    target = LightState(mode="2", brightness=255, white_amount=100, reason="target")
    cmds = commands_for_transition(current, target)
    white_cmds = [c for c in cmds if c.startswith("w")]
    assert white_cmds == ["w100;"]


def test_white_amount_field_optional_defaults_none():
    """LightState without explicit white_amount keeps it None."""
    state = LightState(mode="1", brightness=128, reason="no white")
    assert state.white_amount is None
