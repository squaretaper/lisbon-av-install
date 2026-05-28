import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FIRMWARE = ROOT / "firmware" / "dual_strip_dystopia_test" / "src" / "main.cpp"


def test_dual_strip_firmware_uses_pure_red_pixels_only():
    source = FIRMWARE.read_text()
    assert "CRGB::White" not in source
    for match in re.finditer(r"CRGB\(([^()]*)\)", source):
        args = [part.strip() for part in match.group(1).split(",")]
        if len(args) != 3:
            continue
        assert args[1] == "0" and args[2] == "0", f"non-red CRGB call: {match.group(0)}"


def test_glitch_mode_contains_pure_red_strobe_bursts():
    source = FIRMWARE.read_text()
    assert "strobeGate" in source
    assert "GLITCH STROBE" in source
    assert re.search(r"fill_solid\(stripJ1,\s*NUM_LEDS,\s*CRGB\(2[0-9]{2},\s*0,\s*0\)\)", source)
    assert re.search(r"fill_solid\(stripJ2,\s*NUM_LEDS,\s*CRGB\(2[0-9]{2},\s*0,\s*0\)\)", source)


def test_dual_strip_firmware_exposes_realtime_chase_speed_pulse_and_packet_span_controls():
    source = FIRMWARE.read_text()
    assert "gChaseStepMs" in source
    assert "gPulseDepth" in source
    assert "gPacketSpan" in source
    assert "case '>':" in source
    assert "case '<':" in source
    assert "case ']':" in source
    assert "case '[':" in source
    assert "case '}':" in source
    assert "case '{':" in source


def _function_body(source: str, name: str) -> str:
    match = re.search(rf"void {name}\([^)]*\) \{{", source)
    assert match, f"missing function {name}"
    start = match.end()
    depth = 1
    pos = start
    while pos < len(source) and depth:
        if source[pos] == "{":
            depth += 1
        elif source[pos] == "}":
            depth -= 1
        pos += 1
    return source[start : pos - 1]


def test_chase_mode_uses_black_background_and_small_colliding_packets_not_solid_loop():
    source = FIRMWARE.read_text()
    chase = _function_body(source, "chasePattern")

    assert "CRGB::Black" in chase
    assert "fill_solid(stripJ1, NUM_LEDS, CRGB(breathe" not in chase
    assert "redPacket" in source
    assert "collision" in chase
    assert "gPacketSpan" in chase
    assert "span" in chase
    assert re.search(r"for \(uint8_t\s+k = 0; k < [34];", source)


def test_glitch_mode_has_hard_black_gaps_and_full_bright_red_strobe():
    source = FIRMWARE.read_text()
    glitch = _function_body(source, "glitchPattern")

    assert "blackGate" in glitch
    assert "CRGB(255, 0, 0)" in glitch
    assert "blackout();" in glitch
