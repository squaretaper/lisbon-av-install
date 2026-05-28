#!/usr/bin/env python3
"""Generate a KiCad 10 schematic for the ESP32/WS2811 LED controller.

This deliberately avoids the earlier hand-coded decorative SVG path.  The
output is a real .kicad_sch project that KiCad can open/export.
"""
from __future__ import annotations

import json
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
KICAD_DIR = ROOT / "kicad" / "esp32-led-controller-v6"
PROJECT = "esp32-led-controller-v6"
SCH = KICAD_DIR / f"{PROJECT}.kicad_sch"
PRO = KICAD_DIR / f"{PROJECT}.kicad_pro"


def u() -> str:
    return str(uuid.uuid4())


def q(s: str) -> str:
    return '"' + s.replace('\\', '\\\\').replace('"', '\\"') + '"'


def f(n: float) -> str:
    return f"{n:.3f}".rstrip("0").rstrip(".")


def font(size: float = 1.27) -> str:
    return f"(font (size {f(size)} {f(size)}))"


def prop(name: str, value: str, x: float, y: float, angle: int = 0, hide: bool = False, size: float = 1.27, justify: str = "left") -> str:
    hide_s = "\n      (hide yes)" if hide else ""
    # KiCad accepts left/right/top/bottom justify flags; there is no literal "center" flag.
    justify_s = "" if justify == "center" else f" (justify {justify})"
    return f'''(property {q(name)} {q(value)}
      (at {f(x)} {f(y)} {angle})
      (show_name no){hide_s}
      (do_not_autoplace no)
      (effects {font(size)}{justify_s})
    )'''


def pin(ptype: str, name: str, number: str, x: float, y: float, angle: int, length: float = 7.62, size: float = 1.0) -> str:
    return f'''(pin {ptype} line
        (at {f(x)} {f(y)} {angle})
        (length {f(length)})
        (name {q(name)} (effects {font(size)}))
        (number {q(number)} (effects {font(size)}))
      )'''


def symbol_header(lib_id: str, reference_prefix: str, value: str, description: str = "") -> str:
    return f'''(symbol {q(lib_id)}
      (pin_names (offset 0.762))
      (exclude_from_sim no)
      (in_bom yes)
      (on_board yes)
      (in_pos_files yes)
      (duplicate_pin_numbers_are_jumpers no)
      {prop("Reference", reference_prefix, 0, -9.0, 0, False, 1.27, "center")}
      {prop("Value", value, 0, 9.0, 0, False, 1.27, "center")}
      {prop("Footprint", "", 0, 0, 0, True)}
      {prop("Datasheet", "", 0, 0, 0, True)}
      {prop("Description", description, 0, 0, 0, True)}'''


def lib_symbols() -> str:
    parts: list[str] = []

    # US-style resistor, horizontal.
    parts.append(f'''{symbol_header("Ren:R_US", "R", "R", "Resistor, US zig-zag symbol")}
      (symbol "R_US_0_1"
        (polyline (pts (xy -5.08 0) (xy -3.81 -1.905) (xy -2.54 1.905) (xy -1.27 -1.905) (xy 0 1.905) (xy 1.27 -1.905) (xy 2.54 1.905) (xy 3.81 -1.905) (xy 5.08 0)) (stroke (width 0.254) (type default)) (fill (type none)))
      )
      (symbol "R_US_1_1"
        {pin("passive", "", "1", -8.89, 0, 0, 3.81)}
        {pin("passive", "", "2", 8.89, 0, 180, 3.81)}
      )
      (embedded_fonts no)
    )''')

    # Horizontal fuse.
    parts.append(f'''{symbol_header("Ren:FUSE", "F", "Fuse", "Blade fuse / inline fuse")}
      (symbol "FUSE_0_1"
        (rectangle (start -4.572 -2.032) (end 4.572 2.032) (stroke (width 0.254) (type default)) (fill (type none)))
        (polyline (pts (xy -4.572 0) (xy 4.572 0)) (stroke (width 0.254) (type default)) (fill (type none)))
      )
      (symbol "FUSE_1_1"
        {pin("passive", "", "1", -8.89, 0, 0, 4.318)}
        {pin("passive", "", "2", 8.89, 0, 180, 4.318)}
      )
      (embedded_fonts no)
    )''')

    # Horizontal Schottky diode.
    parts.append(f'''{symbol_header("Ren:D_SCHOTTKY", "D", "D_Schottky", "Schottky diode")}
      (symbol "D_SCHOTTKY_0_1"
        (polyline (pts (xy -3.81 -3.048) (xy -3.81 3.048) (xy 2.032 0) (xy -3.81 -3.048)) (stroke (width 0.254) (type default)) (fill (type none)))
        (polyline (pts (xy 2.032 -3.048) (xy 2.032 3.048)) (stroke (width 0.508) (type default)) (fill (type none)))
        (polyline (pts (xy 2.032 -2.54) (xy 3.302 -3.81)) (stroke (width 0.254) (type default)) (fill (type none)))
        (polyline (pts (xy 2.032 2.54) (xy 0.762 3.81)) (stroke (width 0.254) (type default)) (fill (type none)))
      )
      (symbol "D_SCHOTTKY_1_1"
        {pin("passive", "A", "1", -8.89, 0, 0, 5.08)}
        {pin("passive", "K", "2", 8.89, 0, 180, 6.858)}
      )
      (embedded_fonts no)
    )''')

    # Polar capacitor vertical.
    parts.append(f'''{symbol_header("Ren:C_POL", "C", "C_Polarized", "Polarized capacitor")}
      (symbol "C_POL_0_1"
        (polyline (pts (xy -3.81 -1.27) (xy 3.81 -1.27)) (stroke (width 0.508) (type default)) (fill (type none)))
        (polyline (pts (xy -3.81 1.27) (xy 3.81 1.27)) (stroke (width 0.254) (type default)) (fill (type none)))
        (text "+" (at -5.08 -2.794 0) (effects {font(1.27)}))
      )
      (symbol "C_POL_1_1"
        {pin("passive", "+", "1", 0, 7.62, 270, 5.08)}
        {pin("passive", "-", "2", 0, -7.62, 90, 5.08)}
      )
      (embedded_fonts no)
    )''')

    # Generic cap vertical.
    parts.append(f'''{symbol_header("Ren:C", "C", "C", "Unpolarized capacitor")}
      (symbol "C_0_1"
        (polyline (pts (xy -3.81 -1.27) (xy 3.81 -1.27)) (stroke (width 0.508) (type default)) (fill (type none)))
        (polyline (pts (xy -3.81 1.27) (xy 3.81 1.27)) (stroke (width 0.508) (type default)) (fill (type none)))
      )
      (symbol "C_1_1"
        {pin("passive", "", "1", 0, 7.62, 270, 5.08)}
        {pin("passive", "", "2", 0, -7.62, 90, 5.08)}
      )
      (embedded_fonts no)
    )''')

    # Horizontal LED/diode symbol.
    parts.append(f'''{symbol_header("Ren:LED", "LED", "LED", "Light emitting diode")}
      (symbol "LED_0_1"
        (polyline (pts (xy -3.81 -3.048) (xy -3.81 3.048) (xy 2.032 0) (xy -3.81 -3.048)) (stroke (width 0.254) (type default)) (fill (type none)))
        (polyline (pts (xy 2.032 -3.048) (xy 2.032 3.048)) (stroke (width 0.508) (type default)) (fill (type none)))
        (polyline (pts (xy 3.302 -3.81) (xy 6.35 -6.858)) (stroke (width 0.254) (type default)) (fill (type none)))
        (polyline (pts (xy 4.826 -1.524) (xy 7.874 -4.572)) (stroke (width 0.254) (type default)) (fill (type none)))
      )
      (symbol "LED_1_1"
        {pin("passive", "A", "1", -8.89, 0, 0, 5.08)}
        {pin("passive", "K", "2", 8.89, 0, 180, 6.858)}
      )
      (embedded_fonts no)
    )''')

    # 2-pin connector, pins on left.
    parts.append(f'''{symbol_header("Ren:CONN_2PIN_LEFT", "J", "Conn_2", "Two pin screw terminal")}
      (symbol "CONN_2PIN_LEFT_0_1"
        (rectangle (start -6.35 -6.35) (end 6.35 6.35) (stroke (width 0.254) (type default)) (fill (type none)))
      )
      (symbol "CONN_2PIN_LEFT_1_1"
        {pin("passive", "1", "1", -13.97, 2.54, 0, 7.62)}
        {pin("passive", "2", "2", -13.97, -2.54, 0, 7.62)}
      )
      (embedded_fonts no)
    )''')

    # 3-pin LED output connector, pins on left.
    parts.append(f'''{symbol_header("Ren:CONN_3PIN_LEFT", "J", "Conn_3", "Three pin LED output connector")}
      (symbol "CONN_3PIN_LEFT_0_1"
        (rectangle (start -7.62 -8.89) (end 7.62 8.89) (stroke (width 0.254) (type default)) (fill (type none)))
      )
      (symbol "CONN_3PIN_LEFT_1_1"
        {pin("passive", "V+", "1", -15.24, 5.08, 0, 7.62)}
        {pin("passive", "GND", "2", -15.24, 0, 0, 7.62)}
        {pin("passive", "DATA", "3", -15.24, -5.08, 0, 7.62)}
      )
      (embedded_fonts no)
    )''')

    # ESP32 module, only pins used in this controller.
    parts.append(f'''{symbol_header("Ren:ESP32_DEVKIT_V1_USB_ONLY", "U", "ESP32 DevKit V1", "ESP32 DevKit V1, USB powered only")}
      (symbol "ESP32_DEVKIT_V1_USB_ONLY_0_1"
        (rectangle (start -19.05 -24.13) (end 19.05 24.13) (stroke (width 0.254) (type default)) (fill (type none)))
        (text "ESP32 DevKit V1" (at 0 -6.35 0) (effects {font(1.27)}))
        (text "USB-C powered only" (at 0 0 0) (effects {font(1.016)}))
        (text "VIN/5V = USB tap" (at 0 5.08 0) (effects {font(1.016)}))
      )
      (symbol "ESP32_DEVKIT_V1_USB_ONLY_1_1"
        {pin("power_out", "VIN/5V", "VIN", 27.94, 15.24, 180, 8.89, 1.0)}
        {pin("output", "GPIO25", "G25", 27.94, 7.62, 180, 8.89, 1.0)}
        {pin("output", "GPIO26", "G26", 27.94, 0, 180, 8.89, 1.0)}
        {pin("output", "GPIO27", "G27", 27.94, -7.62, 180, 8.89, 1.0)}
        {pin("power_in", "GND", "GND", 27.94, -15.24, 180, 8.89, 1.0)}
      )
      (embedded_fonts no)
    )''')

    # Physical DIP-14 pinout for SN74AHCT125N top view.
    left_y = [27.0, 18.0, 9.0, 0.0, -9.0, -18.0, -27.0]
    right_y = left_y
    left_pins = [
        ("input", "/OE1", "1"),
        ("input", "1A", "2"),
        ("output", "1Y", "3"),
        ("input", "/OE2", "4"),
        ("input", "2A", "5"),
        ("output", "2Y", "6"),
        ("power_in", "GND", "7"),
    ]
    right_pins = [
        ("power_in", "VCC", "14"),
        ("input", "/OE4", "13"),
        ("input", "4A", "12"),
        ("output", "4Y", "11"),
        ("input", "/OE3", "10"),
        ("input", "3A", "9"),
        ("output", "3Y", "8"),
    ]
    pin_lines = []
    for (ptype, name, num), yy in zip(left_pins, left_y):
        pin_lines.append(pin(ptype, name, num, -33.02, yy, 0, 8.0, 0.95))
    for (ptype, name, num), yy in zip(right_pins, right_y):
        pin_lines.append(pin(ptype, name, num, 33.02, yy, 180, 8.0, 0.95))
    parts.append(f'''{symbol_header("Ren:SN74AHCT125N_DIP14_TOP", "U", "SN74AHCT125N", "74AHCT125 DIP-14 top-view pin-location symbol")}
      (symbol "SN74AHCT125N_DIP14_TOP_0_1"
        (rectangle (start -25.4 -33.02) (end 25.4 33.02) (stroke (width 0.254) (type default)) (fill (type none)))
        (polyline (pts (xy -5.08 33.02) (xy -2.54 36.83) (xy 2.54 36.83) (xy 5.08 33.02)) (stroke (width 0.254) (type default)) (fill (type none)))
        (text "SN74AHCT125N" (at 0 -6.35 0) (effects {font(1.27)}))
        (text "DIP-14 TOP VIEW" (at 0 0 0) (effects {font(1.016)}))
        (text "notch up / pin 1 upper-left" (at 0 5.08 0) (effects {font(0.9)}))
      )
      (symbol "SN74AHCT125N_DIP14_TOP_1_1"
        {' '.join(pin_lines)}
      )
      (embedded_fonts no)
    )''')

    return "\n".join(parts)


def instance(lib_id: str, ref: str, value: str, x: float, y: float, pins: list[str], footprint: str = "", datasheet: str = "", description: str = "", rotation: int = 0, project_uuid: str = "") -> str:
    sym_uuid = u()
    pin_entries = "\n".join(f'    (pin {q(p)} (uuid {q(u())}))' for p in pins)
    ref_y = y - 11
    val_y = y + 11
    if lib_id.endswith("ESP32_DEVKIT_V1_USB_ONLY"):
        ref_y = y - 31
        val_y = y + 31
    if lib_id.endswith("SN74AHCT125N_DIP14_TOP"):
        ref_y = y - 45
        val_y = y + 45
    return f'''(symbol
    (lib_id {q(lib_id)})
    (at {f(x)} {f(y)} {rotation})
    (unit 1)
    (body_style 1)
    (exclude_from_sim no)
    (in_bom yes)
    (on_board yes)
    (in_pos_files yes)
    (dnp no)
    (uuid {q(sym_uuid)})
    {prop("Reference", ref, x, ref_y, 0, False, 1.27, "center")}
    {prop("Value", value, x, val_y, 0, False, 1.27, "center")}
    {prop("Footprint", footprint, x, y, 0, True, 1.0)}
    {prop("Datasheet", datasheet, x, y, 0, True, 1.0)}
    {prop("Description", description, x, y, 0, True, 1.0)}
{pin_entries}
    (instances
      (project {q(PROJECT)}
        (path {q('/' + project_uuid)}
          (reference {q(ref)})
          (unit 1)
        )
      )
    )
  )'''


def wire(x1: float, y1: float, x2: float, y2: float) -> str:
    return f'''(wire
    (pts (xy {f(x1)} {f(y1)}) (xy {f(x2)} {f(y2)}))
    (stroke (width 0) (type solid))
    (uuid {q(u())})
  )'''


def label(text: str, x: float, y: float, angle: int = 0, justify: str = "left bottom", size: float = 1.27) -> str:
    return f'''(label {q(text)}
    (at {f(x)} {f(y)} {angle})
    (effects {font(size)} (justify {justify}))
    (uuid {q(u())})
  )'''


def text_block(text: str, x: float, y: float, size: float = 1.27, bold: bool = False) -> str:
    # KiCad schematic text accepts backslash-n line breaks in quoted strings.
    style = " (bold yes)" if bold else ""
    return f'''(text {q(text)}
    (exclude_from_sim no)
    (at {f(x)} {f(y)} 0)
    (effects (font (size {f(size)} {f(size)}){style}) (justify left bottom))
    (uuid {q(u())})
  )'''


def no_connect(x: float, y: float) -> str:
    return f'''(no_connect
    (at {f(x)} {f(y)})
    (uuid {q(u())})
  )'''


def label_stub(pin_x: float, pin_y: float, lab: str, side: str, length: float = 10.0) -> list[str]:
    if side == "left":
        lx = pin_x - length
        return [wire(pin_x, pin_y, lx, pin_y), label(lab, lx, pin_y, 180, "right bottom")]
    if side == "right":
        lx = pin_x + length
        return [wire(pin_x, pin_y, lx, pin_y), label(lab, lx, pin_y, 0, "left bottom")]
    if side == "up":
        ly = pin_y - length
        return [wire(pin_x, pin_y, pin_x, ly), label(lab, pin_x, ly, 90, "left bottom")]
    if side == "down":
        ly = pin_y + length
        return [wire(pin_x, pin_y, pin_x, ly), label(lab, pin_x, ly, 270, "left bottom")]
    raise ValueError(side)


def make_schematic() -> str:
    root_uuid = u()
    objects: list[str] = []

    # Title and section notes.
    objects.append(text_block("ESP32 LED Controller v6 — KiCad bench schematic", 18, 18, 2.2, True))
    objects.append(text_block("Rails: +12V_PROTECTED powers LED V+ only. +5V_LOGIC is USB-derived from ESP32 VIN/5V only. Grounds are common.", 18, 25, 1.15))

    # Main symbols.
    objects.append(instance("Ren:ESP32_DEVKIT_V1_USB_ONLY", "U2", "ESP32 DevKit V1 / USB only", 62, 82, ["VIN", "G25", "G26", "G27", "GND"], footprint="", description="USB-powered ESP32 devkit", project_uuid=root_uuid))
    objects.append(instance("Ren:SN74AHCT125N_DIP14_TOP", "U1", "SN74AHCT125N / 74AHCT125 DIP-14", 200, 105, ["1","2","3","4","5","6","7","8","9","10","11","12","13","14"], footprint="Package_DIP:DIP-14_W7.62mm_LongPads", datasheet="https://www.ti.com/lit/ds/symlink/sn74ahct125.pdf", project_uuid=root_uuid))
    objects.append(instance("Ren:R_US", "R1", "470Ω", 294, 96, ["1", "2"], footprint="Resistor_THT:R_Axial_DIN0207_L6.3mm_D2.5mm_P10.16mm_Horizontal", description="Series data resistor for J1", project_uuid=root_uuid))
    objects.append(instance("Ren:R_US", "R2", "470Ω", 294, 113, ["1", "2"], footprint="Resistor_THT:R_Axial_DIN0207_L6.3mm_D2.5mm_P10.16mm_Horizontal", description="Series data resistor for J2", project_uuid=root_uuid))
    objects.append(instance("Ren:CONN_3PIN_LEFT", "J1", "LED OUT 1", 372, 82, ["1","2","3"], footprint="TerminalBlock:TerminalBlock_bornier-3_P5.08mm", description="LED strip output 1: V+, GND, DATA", project_uuid=root_uuid))
    objects.append(instance("Ren:CONN_3PIN_LEFT", "J2", "LED OUT 2", 372, 124, ["1","2","3"], footprint="TerminalBlock:TerminalBlock_bornier-3_P5.08mm", description="LED strip output 2: V+, GND, DATA", project_uuid=root_uuid))

    # ESP32 stubs (pins are at x=62+27.94)
    esp_x = 62 + 27.94
    for y, lab in [(82-15.24, "+5V_LOGIC"), (82-7.62, "ESP32_GPIO25"), (82, "ESP32_GPIO26"), (82+7.62, "ESP32_GPIO27"), (82+15.24, "GND")]:
        objects.extend(label_stub(esp_x, y, lab, "right", 13))

    # U1 pin stubs. Left pins at x=200-33.02. Right pins at x=200+33.02.
    ux_l = 200 - 33.02
    ux_r = 200 + 33.02
    uy = {1:78, 2:87, 3:96, 4:105, 5:114, 6:123, 7:132, 14:78, 13:87, 12:96, 11:105, 10:114, 9:123, 8:132}
    u1_left_labels = {
        1: "GND",       # /OE1 low = enabled
        2: "ESP32_GPIO25",
        3: "U1_1Y",
        4: "GND",       # /OE2 low = enabled
        5: "ESP32_GPIO26",
        6: "U1_2Y",
        7: "GND",
    }
    for p, lab in u1_left_labels.items():
        objects.extend(label_stub(ux_l, uy[p], lab, "left", 15))
    u1_right_labels = {
        14: "+5V_LOGIC",
        13: "+5V_LOGIC",  # /OE4 high = disabled
        12: "GND",
        10: "+5V_LOGIC",  # /OE3 high = disabled
        9: "GND",
    }
    for p, lab in u1_right_labels.items():
        objects.extend(label_stub(ux_r, uy[p], lab, "right", 15))
    # Disabled outputs 4Y and 3Y are NC.
    objects.append(no_connect(ux_r, uy[11]))
    objects.append(no_connect(ux_r, uy[8]))
    objects.append(text_block("U1 unused channels: /OE3 pin10 and /OE4 pin13 → +5V_LOGIC; 3A pin9 and 4A pin12 → GND; 3Y pin8 and 4Y pin11 NC.", 142, 160, 1.05))

    # Output resistors connect U1_1Y/U1_2Y to J1_DATA/J2_DATA by labels.
    # R1 pins: local x ±8.89, R1 at x=294.
    for ry, left_lab, right_lab in [(96, "U1_1Y", "J1_DATA"), (113, "U1_2Y", "J2_DATA")]:
        objects.extend(label_stub(294-8.89, ry, left_lab, "left", 12))
        objects.extend(label_stub(294+8.89, ry, right_lab, "right", 12))

    # LED output connectors, pins on left at x=372-15.24; y offsets -5.08, 0, +5.08.
    jx = 372 - 15.24
    for base_y, prefix in [(82, "J1"), (124, "J2")]:
        objects.extend(label_stub(jx, base_y-5.08, "+12V_PROTECTED", "left", 12))
        objects.extend(label_stub(jx, base_y, "GND", "left", 12))
        objects.extend(label_stub(jx, base_y+5.08, f"{prefix}_DATA", "left", 12))

    # 12 V power input/protection chain.
    objects.append(text_block("12 V POWER INPUT / PROTECTION", 20, 168, 1.35, True))
    objects.append(instance("Ren:CONN_2PIN_LEFT", "J3", "12V IN", 42, 190, ["1","2"], footprint="TerminalBlock:TerminalBlock_bornier-2_P5.08mm", description="12 V input screw terminal", project_uuid=root_uuid))
    objects.append(instance("Ren:FUSE", "F1", "7.5A blade / off-board inline", 92, 187.46, ["1","2"], description="Off-board inline blade fuse", project_uuid=root_uuid))
    objects.append(instance("Ren:D_SCHOTTKY", "D1", "1N5822? REVIEW CURRENT", 142, 187.46, ["1","2"], footprint="Diode_THT:D_DO-201AD_P15.24mm_Horizontal", description="Reverse polarity diode; current/thermal rating must be reviewed", project_uuid=root_uuid))
    # J3 pin coords: x=42-13.97, y=190±2.54. Use labels/wires.
    objects.extend(label_stub(42-13.97, 190-2.54, "+12V_IN", "left", 12))
    objects.extend(label_stub(42-13.97, 190+2.54, "GND", "left", 12))
    # Wire chain + labels.
    objects.append(wire(54, 187.46, 83.11, 187.46))
    objects.append(label("+12V_IN", 54, 187.46, 0, "left bottom"))
    objects.append(wire(100.89, 187.46, 133.11, 187.46))
    objects.append(wire(150.89, 187.46, 181, 187.46))
    objects.append(label("+12V_PROTECTED", 181, 187.46, 0, "left bottom"))
    objects.append(text_block("D1 current note: 1N5822 is not a free pass for multi-amp LED current. For full-current install, replace with rated protection or bypass if polarity is controlled.", 20, 216, 1.05))

    # Bulk cap and power-good LED branch.
    objects.append(instance("Ren:C_POL", "C1", "1000µF / 25V", 218, 194, ["1","2"], footprint="Capacitor_THT:CP_Radial_D10.0mm_P5.00mm", description="12 V bulk smoothing capacitor", project_uuid=root_uuid))
    objects.extend(label_stub(218, 194-7.62, "+12V_PROTECTED", "up", 9))
    objects.extend(label_stub(218, 194+7.62, "GND", "down", 9))

    objects.append(instance("Ren:R_US", "R4", "1kΩ", 268, 187, ["1","2"], description="Power-good LED resistor", project_uuid=root_uuid))
    objects.append(instance("Ren:LED", "LED2", "green power-good", 312, 187, ["1","2"], description="12 V power-good LED", project_uuid=root_uuid))
    objects.extend(label_stub(268-8.89, 187, "+12V_PROTECTED", "left", 10))
    objects.append(wire(268+8.89, 187, 312-8.89, 187))
    objects.extend(label_stub(312+8.89, 187, "GND", "right", 10))

    # 5 V decoupling and status LED.
    objects.append(text_block("5 V LOGIC / STATUS", 20, 230, 1.35, True))
    objects.append(instance("Ren:C", "C2", "0.1µF", 80, 248, ["1","2"], description="U1 high-frequency decoupling", project_uuid=root_uuid))
    objects.append(instance("Ren:C", "C3", "10µF", 118, 248, ["1","2"], description="U1 mid-frequency decoupling", project_uuid=root_uuid))
    for cx in [80, 118]:
        objects.extend(label_stub(cx, 248-7.62, "+5V_LOGIC", "up", 8))
        objects.extend(label_stub(cx, 248+7.62, "GND", "down", 8))
    objects.append(instance("Ren:R_US", "R3", "220Ω", 180, 248, ["1","2"], description="GPIO27 status LED resistor", project_uuid=root_uuid))
    objects.append(instance("Ren:LED", "LED1", "red status", 224, 248, ["1","2"], description="Firmware controlled status LED", project_uuid=root_uuid))
    objects.extend(label_stub(180-8.89, 248, "ESP32_GPIO27", "left", 12))
    objects.append(wire(180+8.89, 248, 224-8.89, 248))
    objects.extend(label_stub(224+8.89, 248, "GND", "right", 12))

    # Bottom safety notes.
    objects.append(text_block("Bench checks before power: +12V_PROTECTED ↔ +5V_LOGIC = open/megaohms; all GND points ≈0Ω; U1 pin14 gets +5V only from ESP32 USB/VIN; never backfeed ESP32 VIN from 12 V supply.", 20, 276, 1.05))

    sch = f'''(kicad_sch
  (version 20260101)
  (generator "ren-generate-kicad-schematic")
  (generator_version "1.0")
  (uuid {q(root_uuid)})
  (paper "A3")
  (title_block
    (title "ESP32 LED Controller v6 — KiCad Bench Schematic")
    (date "2026-05-20")
    (rev "v6-kicad-1")
    (company "Lisbon AV installation")
    (comment 1 "ESP32 USB-powered only; common GND; AHCT125 DIP-14 top-view shown for bench wiring")
  )
  (lib_symbols
    {lib_symbols()}
  )
  {' '.join(objects)}
  (sheet_instances
    (path "/" (page "1"))
  )
  (embedded_fonts no)
)
'''
    return sch


def main() -> None:
    KICAD_DIR.mkdir(parents=True, exist_ok=True)
    SCH.write_text(make_schematic(), encoding="utf-8")
    PRO.write_text(json.dumps({"meta": {"version": 1}, "schematic": {}}, indent=2) + "\n", encoding="utf-8")
    print(SCH)
    print(PRO)


if __name__ == "__main__":
    main()
