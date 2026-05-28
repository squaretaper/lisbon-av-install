#!/usr/bin/env python3
"""Generate the reviewed standard KiCad schematic for the ESP32 LED controller.

This sheet is intentionally different from the DIP-14 bench pinout sheet:
- U1 is a standard multi-unit logic schematic part: U1A/U1B/U1C/U1D + U1P.
- The full part number SN74AHCT125N is displayed prominently, not hidden in tiny value text.
- Net names match docs/esp32-breadboard/netlist.json.
- The rejected 1N5822 full-current diode is not used; RP1 is the verified high-current
  reverse-polarity protection block from the audited netlist.
"""
from __future__ import annotations

import json
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
KICAD_DIR = ROOT / "kicad" / "esp32-led-controller-v6-standard"
PROJECT = "esp32-led-controller-v6-standard"
SCH = KICAD_DIR / f"{PROJECT}.kicad_sch"
PRO = KICAD_DIR / f"{PROJECT}.kicad_pro"


def u() -> str:
    return str(uuid.uuid4())


def q(s: str) -> str:
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'


def f(n: float) -> str:
    return f"{n:.3f}".rstrip("0").rstrip(".")


def font(size: float = 1.27, bold: bool = False) -> str:
    b = " (bold yes)" if bold else ""
    return f"(font (size {f(size)} {f(size)}){b})"


def prop(name: str, value: str, x: float, y: float, angle: int = 0, hide: bool = False,
         size: float = 1.27, justify: str = "left") -> str:
    hide_s = "\n      (hide yes)" if hide else ""
    justify_s = "" if justify == "center" else f" (justify {justify})"
    return f'''(property {q(name)} {q(value)}
      (at {f(x)} {f(y)} {angle})
      (show_name no){hide_s}
      (do_not_autoplace no)
      (effects {font(size)}{justify_s})
    )'''


def pin(ptype: str, name: str, number: str, x: float, y: float, angle: int,
        length: float = 5.08, shape: str = "line", size: float = 1.15) -> str:
    return f'''(pin {ptype} {shape}
        (at {f(x)} {f(y)} {angle})
        (length {f(length)})
        (name {q(name)} (effects {font(size)}))
        (number {q(number)} (effects {font(size)}))
      )'''


def symbol_header(lib_id: str, reference_prefix: str, value: str, description: str = "",
                  pin_offset: float = 0.762) -> str:
    return f'''(symbol {q(lib_id)}
      (pin_names (offset {f(pin_offset)}))
      (exclude_from_sim no)
      (in_bom yes)
      (on_board yes)
      (in_pos_files yes)
      (duplicate_pin_numbers_are_jumpers no)
      {prop("Reference", reference_prefix, 0, -8.0, 0, False, 1.27, "center")}
      {prop("Value", value, 0, 8.0, 0, False, 1.27, "center")}
      {prop("Footprint", "", 0, 0, 0, True)}
      {prop("Datasheet", "", 0, 0, 0, True)}
      {prop("Description", description, 0, 0, 0, True)}'''


def ahct_gate_symbol(lib_id: str, oe_name: str, oe_pin: str, a_name: str, a_pin: str,
                     y_name: str, y_pin: str) -> str:
    # Large gate symbol: unmistakable on a printed A3 or quick bench preview.
    a_type = "passive" if lib_id.endswith(("CH3", "CH4")) else "input"
    return f'''{symbol_header(lib_id, "U", "SN74AHCT125N", "One gate of SN74AHCT125N quad tri-state buffer", 1.016)}
      (symbol "{lib_id.split(':')[-1]}_0_1"
        (polyline (pts (xy -7.62 -7.62) (xy -7.62 7.62) (xy 7.62 0) (xy -7.62 -7.62)) (stroke (width 0.254) (type default)) (fill (type background)))
        (text "AHCT125" (at 0 0 0) (effects {font(1.0, True)}))
      )
      (symbol "{lib_id.split(':')[-1]}_1_1"
        {pin(a_type, a_name, a_pin, -20.32, 0, 0, 7.62, "line", 1.2)}
        {pin("tri_state", y_name, y_pin, 20.32, 0, 180, 7.62, "line", 1.2)}
        {pin("passive", oe_name, oe_pin, 0, 15.24, 270, 7.62, "inverted", 1.2)}
      )
      (embedded_fonts no)
    )'''


def lib_symbols() -> str:
    parts: list[str] = []

    parts.append(f'''{symbol_header("RenStd:R_US", "R", "R", "Resistor, US zig-zag symbol")}
      (symbol "R_US_0_1"
        (polyline (pts (xy -5.08 0) (xy -3.81 -1.905) (xy -2.54 1.905) (xy -1.27 -1.905) (xy 0 1.905) (xy 1.27 -1.905) (xy 2.54 1.905) (xy 3.81 -1.905) (xy 5.08 0)) (stroke (width 0.254) (type default)) (fill (type none)))
      )
      (symbol "R_US_1_1"
        {pin("passive", "", "1", -8.89, 0, 0, 3.81)}
        {pin("passive", "", "2", 8.89, 0, 180, 3.81)}
      )
      (embedded_fonts no)
    )''')

    parts.append(f'''{symbol_header("RenStd:FUSE", "F", "Fuse", "Blade fuse / inline fuse")}
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

    parts.append(f'''{symbol_header("RenStd:REV_PROT", "RP", "Reverse protection", "High-current reverse-polarity protection block")}
      (symbol "REV_PROT_0_1"
        (rectangle (start -10.16 -6.35) (end 10.16 6.35) (stroke (width 0.254) (type default)) (fill (type background)))
        (text "REV" (at 0 -2.2 0) (effects {font(1.05, True)}))
        (text "PROT" (at 0 2.2 0) (effects {font(1.05, True)}))
      )
      (symbol "REV_PROT_1_1"
        {pin("passive", "IN", "1", -15.24, 0, 0, 5.08)}
        {pin("passive", "OUT", "2", 15.24, 0, 180, 5.08)}
      )
      (embedded_fonts no)
    )''')

    parts.append(f'''{symbol_header("RenStd:C", "C", "C", "Unpolarized capacitor")}
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

    parts.append(f'''{symbol_header("RenStd:C_POL", "C", "C_Polarized", "Polarized capacitor")}
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

    parts.append(f'''{symbol_header("RenStd:LED", "LED", "LED", "Light emitting diode")}
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

    parts.append(f'''{symbol_header("RenStd:CONN_2_RIGHT", "J", "Conn_2", "Two pin connector, pins face right")}
      (symbol "CONN_2_RIGHT_0_1"
        (rectangle (start -6.35 -6.35) (end 6.35 6.35) (stroke (width 0.254) (type default)) (fill (type none)))
      )
      (symbol "CONN_2_RIGHT_1_1"
        {pin("passive", "+", "1", 13.97, 2.54, 180, 7.62)}
        {pin("passive", "GND", "2", 13.97, -2.54, 180, 7.62)}
      )
      (embedded_fonts no)
    )''')

    parts.append(f'''{symbol_header("RenStd:CONN_3_LEFT", "J", "Conn_3", "Three pin connector, pins face left")}
      (symbol "CONN_3_LEFT_0_1"
        (rectangle (start -7.62 -8.89) (end 7.62 8.89) (stroke (width 0.254) (type default)) (fill (type none)))
      )
      (symbol "CONN_3_LEFT_1_1"
        {pin("passive", "V+", "1", -15.24, 5.08, 0, 7.62)}
        {pin("passive", "GND", "2", -15.24, 0, 0, 7.62)}
        {pin("passive", "DATA", "3", -15.24, -5.08, 0, 7.62)}
      )
      (embedded_fonts no)
    )''')

    parts.append(f'''{symbol_header("RenStd:ESP32_DEVKIT_V1_USB_ONLY", "U", "ESP32 DevKit V1", "ESP32 DevKit V1, USB powered only")}
      (symbol "ESP32_DEVKIT_V1_USB_ONLY_0_1"
        (rectangle (start -17.78 -24.13) (end 17.78 24.13) (stroke (width 0.254) (type default)) (fill (type background)))
        (text "ESP32 DevKit V1" (at 0 -6.35 0) (effects {font(1.45, True)}))
        (text "USB-C POWER ONLY" (at 0 0 0) (effects {font(1.15, True)}))
        (text "VIN/5V = USB tap" (at 0 6.35 0) (effects {font(1.05)}))
        (text "DO NOT BACKFEED" (at 0 11.43 0) (effects {font(1.05, True)}))
      )
      (symbol "ESP32_DEVKIT_V1_USB_ONLY_1_1"
        {pin("power_out", "VIN/5V", "VIN", 25.4, 15.24, 180, 7.62)}
        {pin("output", "GPIO25", "G25", 25.4, 7.62, 180, 7.62)}
        {pin("output", "GPIO26", "G26", 25.4, 0, 180, 7.62)}
        {pin("output", "GPIO27", "G27", 25.4, -7.62, 180, 7.62)}
        {pin("passive", "GND", "GND", 25.4, -17.78, 180, 7.62)}
      )
      (embedded_fonts no)
    )''')

    parts.append(ahct_gate_symbol("RenStd:AHCT125_CH1", "~{OE1}", "1", "1A", "2", "1Y", "3"))
    parts.append(ahct_gate_symbol("RenStd:AHCT125_CH2", "~{OE2}", "4", "2A", "5", "2Y", "6"))
    parts.append(ahct_gate_symbol("RenStd:AHCT125_CH3", "~{OE3}", "10", "3A", "9", "3Y", "8"))
    parts.append(ahct_gate_symbol("RenStd:AHCT125_CH4", "~{OE4}", "13", "4A", "12", "4Y", "11"))

    parts.append(f'''{symbol_header("RenStd:AHCT125_PWR", "U", "SN74AHCT125N power", "SN74AHCT125N power pins")}
      (symbol "AHCT125_PWR_0_1"
        (rectangle (start -10.16 -10.16) (end 10.16 10.16) (stroke (width 0.254) (type default)) (fill (type background)))
        (text "U1P" (at 0 -3.0 0) (effects {font(1.3, True)}))
        (text "SN74AHCT125N" (at 0 2.0 0) (effects {font(1.0, True)}))
      )
      (symbol "AHCT125_PWR_1_1"
        {pin("passive", "VCC", "14", 0, 15.24, 270, 5.08, "line", 1.2)}
        {pin("passive", "GND", "7", 0, -15.24, 90, 5.08, "line", 1.2)}
      )
      (embedded_fonts no)
    )''')

    parts.append(f'''{symbol_header("RenStd:TP", "TP", "Test point", "One pin test point")}
      (symbol "TP_0_1"
        (circle (center 0 0) (radius 1.27) (stroke (width 0.254) (type default)) (fill (type none)))
      )
      (symbol "TP_1_1"
        {pin("passive", "TP", "1", -1.27, 0, 0, 1.27, "line", 0.8)}
      )
      (embedded_fonts no)
    )''')

    return "\n".join(parts)


def instance(lib_id: str, ref: str, value: str, x: float, y: float, pins: list[str],
             footprint: str = "", datasheet: str = "", description: str = "",
             rotation: int = 0, project_uuid: str = "", hide_value: bool = False) -> str:
    sym_uuid = u()
    pin_entries = "\n".join(f'    (pin {q(p)} (uuid {q(u())}))' for p in pins)

    ref_size = 1.35
    val_size = 1.16
    ref_y = y - 11.5
    val_y = y + 11.5
    if lib_id.endswith("ESP32_DEVKIT_V1_USB_ONLY"):
        ref_y, val_y, ref_size, val_size = y - 31, y + 31, 1.6, 1.25
    if "AHCT125_CH" in lib_id:
        ref_y, val_y, ref_size, val_size = y - 21, y + 20, 2.0, 1.55
    if lib_id.endswith("AHCT125_PWR"):
        ref_y, val_y, ref_size, val_size = y - 18, y + 18, 1.8, 1.35
    if lib_id.endswith("TP"):
        ref_y, val_y, ref_size, val_size, hide_value = y - 4, y + 4, 1.0, 0.8, True

    in_bom = "no" if ref.startswith("TP") else "yes"
    on_board = "yes"
    return f'''(symbol
    (lib_id {q(lib_id)})
    (at {f(x)} {f(y)} {rotation})
    (unit 1)
    (body_style 1)
    (exclude_from_sim no)
    (in_bom {in_bom})
    (on_board {on_board})
    (in_pos_files yes)
    (dnp no)
    (uuid {q(sym_uuid)})
    {prop("Reference", ref, x, ref_y, 0, False, ref_size, "center")}
    {prop("Value", value, x, val_y, 0, hide_value, val_size, "center")}
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
    return f'''(text {q(text)}
    (exclude_from_sim no)
    (at {f(x)} {f(y)} 0)
    (effects {font(size, bold)} (justify left bottom))
    (uuid {q(u())})
  )'''


def text_lines(lines: list[str], x: float, y: float, size: float = 1.27, bold: bool = False, spacing: float | None = None) -> list[str]:
    if spacing is None:
        spacing = size * 2.25
    return [text_block(line, x, y + i * spacing, size, bold) for i, line in enumerate(lines)]


def no_connect(x: float, y: float) -> str:
    return f'''(no_connect
    (at {f(x)} {f(y)})
    (uuid {q(u())})
  )'''


def label_stub(pin_x: float, pin_y: float, lab: str, side: str, length: float = 9.0, size: float = 1.27) -> list[str]:
    if side == "left":
        lx = pin_x - length
        return [wire(pin_x, pin_y, lx, pin_y), label(lab, lx, pin_y, 180, "right bottom", size)]
    if side == "right":
        lx = pin_x + length
        return [wire(pin_x, pin_y, lx, pin_y), label(lab, lx, pin_y, 0, "left bottom", size)]
    if side == "up":
        ly = pin_y - length
        return [wire(pin_x, pin_y, pin_x, ly), label(lab, pin_x, ly, 90, "left bottom", size)]
    if side == "down":
        ly = pin_y + length
        return [wire(pin_x, pin_y, pin_x, ly), label(lab, pin_x, ly, 270, "left bottom", size)]
    raise ValueError(side)


def make_schematic() -> str:
    root_uuid = u()
    o: list[str] = []

    o.append(text_block("ESP32 LED Controller v6 — reviewed standard KiCad schematic", 18, 18, 2.25, True))
    o.append(text_block("Verified netlist names match docs/esp32-breadboard/netlist.json. 12 V LED rail and USB 5 V logic rail are isolated except GND_COMMON.", 18, 27, 1.25))

    # Explicit U1 callout: fixes the previous ambiguity where U1A/U1B were too easy to miss.
    o.append(text_block("CONTROL + LEVEL SHIFT — U1 SN74AHCT125N", 18, 43, 1.65, True))
    o.extend(text_lines([
        "U1 = SN74AHCT125N DIP-14 quad AHCT tri-state buffer",
        "Units: U1A/U1B used, U1C/U1D disabled, U1P power pins 14/7",
        "OE1/OE2 -> GND; OE3/OE4 -> P5_LOGIC_USB."
    ], 222, 39, 1.18, True, 3.4))

    # ESP32 controller.
    o.append(instance("RenStd:ESP32_DEVKIT_V1_USB_ONLY", "U2", "ESP32 DevKit V1", 50, 92,
                      ["VIN", "G25", "G26", "G27", "GND"],
                      description="USB powered only; VIN/5V is an output tap", project_uuid=root_uuid))
    esp_x = 50 + 25.4
    for yy, lab in [
        (92-15.24, "P5_LOGIC_USB"),
        (92-7.62, "GPIO25_TO_U1_1A"),
        (92, "GPIO26_TO_U1_2A"),
        (92+7.62, "GPIO27_STATUS"),
        (92+17.78, "GND_COMMON"),
    ]:
        o.extend(label_stub(esp_x, yy, lab, "right", 13, 1.18))

    # Used AHCT125 channels. Coordinates line up with resistors/connectors to make the signal chain obvious.
    u1a_y = 78.08
    u1b_y = 116.08
    u1_x = 150
    o.append(instance("RenStd:AHCT125_CH1", "U1A", "SN74AHCT125N", u1_x, u1a_y, ["1","2","3"],
                      footprint="Package_DIP:DIP-14_W7.62mm_LongPads",
                      datasheet="https://www.ti.com/lit/ds/symlink/sn74ahct125.pdf",
                      description="SN74AHCT125N channel 1; J1 data buffer", project_uuid=root_uuid))
    o.append(instance("RenStd:AHCT125_CH2", "U1B", "SN74AHCT125N", u1_x, u1b_y, ["4","5","6"],
                      footprint="Package_DIP:DIP-14_W7.62mm_LongPads",
                      datasheet="https://www.ti.com/lit/ds/symlink/sn74ahct125.pdf",
                      description="SN74AHCT125N channel 2; J2 data buffer", project_uuid=root_uuid))

    # U1A/U1B input, output, and /OE nets.
    for y, gpio_net, out_net in [
        (u1a_y, "GPIO25_TO_U1_1A", "U1_1Y_TO_R1"),
        (u1b_y, "GPIO26_TO_U1_2A", "U1_2Y_TO_R2"),
    ]:
        o.extend(label_stub(u1_x-20.32, y, gpio_net, "left", 17, 1.15))
        o.extend(label_stub(u1_x, y-15.24, "GND_COMMON", "up", 11, 1.1))
        # Short output net label before resistor.
        o.extend(label_stub(u1_x+20.32, y, out_net, "right", 7, 1.05))

    # Series resistors and output connectors with continuous visible wires.
    r_x = 214
    j_x = 332
    o.append(instance("RenStd:R_US", "R1", "470Ω", r_x, u1a_y, ["1","2"], description="J1 data series resistor", project_uuid=root_uuid))
    o.append(instance("RenStd:R_US", "R2", "470Ω", r_x, u1b_y, ["1","2"], description="J2 data series resistor", project_uuid=root_uuid))
    # Output wires from U1 to R and R to connectors.
    for y, out_net, data_net, tp_ref in [
        (u1a_y, "U1_1Y_TO_R1", "J1_DATA", "TP3"),
        (u1b_y, "U1_2Y_TO_R2", "J2_DATA", "TP4"),
    ]:
        tp_x = 263
        tp_pin_x = tp_x - 1.27
        o.append(wire(u1_x+20.32, y, r_x-8.89, y))
        o.append(wire(r_x+8.89, y, tp_pin_x, y))
        o.append(wire(tp_pin_x, y, j_x-15.24, y))
        o.append(instance("RenStd:TP", tp_ref, data_net, tp_x, y, ["1"], description=f"{data_net} test point", project_uuid=root_uuid, hide_value=True))
        o.append(label(data_net, 271, y, 0, "left bottom", 1.05))

    o.append(instance("RenStd:CONN_3_LEFT", "J1", "LED OUT 1", j_x, u1a_y-5.08, ["1","2","3"],
                      footprint="TerminalBlock:TerminalBlock_bornier-3_P5.08mm", description="LED output 1: V+, GND, DATA", project_uuid=root_uuid))
    o.append(instance("RenStd:CONN_3_LEFT", "J2", "LED OUT 2", j_x, u1b_y-5.08, ["1","2","3"],
                      footprint="TerminalBlock:TerminalBlock_bornier-3_P5.08mm", description="LED output 2: V+, GND, DATA", project_uuid=root_uuid))
    jpin_x = j_x - 15.24
    for center_y, prefix in [(u1a_y-5.08, "J1"), (u1b_y-5.08, "J2")]:
        # Connector pin coordinates: V+ center_y-5.08, GND center_y, DATA center_y+5.08.
        o.extend(label_stub(jpin_x, center_y-5.08, "P12_PROTECTED", "left", 13, 1.1))
        o.extend(label_stub(jpin_x, center_y, "GND_COMMON", "left", 13, 1.1))
        # DATA is already on the continuous wire; add a small printed note only.
        o.append(text_block(f"{prefix} DATA", jpin_x-21, center_y+5.08-2.0, 0.95))

    # Status LED, spaced away from U1 gates.
    o.append(text_block("ESP32 STATUS LED", 18, 137, 1.35, True))
    o.append(instance("RenStd:R_US", "R3", "220Ω", 60, 154, ["1","2"], description="GPIO27 status LED resistor", project_uuid=root_uuid))
    o.append(instance("RenStd:LED", "LED1", "red status", 102, 154, ["1","2"], description="Firmware controlled status LED", project_uuid=root_uuid))
    o.extend(label_stub(60-8.89, 154, "GPIO27_STATUS", "left", 13, 1.1))
    o.append(wire(60+8.89, 154, 102-8.89, 154))
    o.append(label("STATUS_LED_SERIES", 76, 154, 0, "left bottom", 0.95))
    o.extend(label_stub(102+8.89, 154, "GND_COMMON", "right", 12, 1.1))

    # U1 power, decoupling, unused gates. This is below the data path and clearly labeled.
    o.append(text_block("U1 SN74AHCT125N POWER + UNUSED GATES", 18, 180, 1.55, True))
    o.append(instance("RenStd:AHCT125_PWR", "U1P", "SN74AHCT125N power", 55, 215, ["14","7"],
                      footprint="Package_DIP:DIP-14_W7.62mm_LongPads", datasheet="https://www.ti.com/lit/ds/symlink/sn74ahct125.pdf", project_uuid=root_uuid,
                      hide_value=True))
    o.extend(label_stub(55, 215-15.24, "P5_LOGIC_USB", "left", 13, 1.15))
    o.extend(label_stub(55, 215+15.24, "GND_COMMON", "left", 13, 1.15))
    o.append(text_block("U1P: pin 14 VCC, pin 7 GND", 18, 239, 1.0))
    o.append(instance("RenStd:C", "C2", "0.1µF", 108, 215, ["1","2"], description="U1 HF decoupling directly at pins 14/7", project_uuid=root_uuid))
    o.append(instance("RenStd:C", "C3", "10µF", 145, 215, ["1","2"], description="U1 local reservoir capacitor", project_uuid=root_uuid))
    cap_top_y = 215-7.62
    cap_bot_y = 215+7.62
    o.append(wire(108, cap_top_y, 145, cap_top_y))
    o.append(wire(108, cap_bot_y, 145, cap_bot_y))
    o.extend(label_stub(108, cap_top_y, "P5_LOGIC_USB", "left", 12, 1.05))
    o.extend(label_stub(108, cap_bot_y, "GND_COMMON", "left", 12, 1.05))
    tp2_x = 166
    tp2_pin_x = tp2_x - 1.27
    o.append(instance("RenStd:TP", "TP2", "P5_LOGIC_USB", tp2_x, 199, ["1"], description="5 V logic test point", project_uuid=root_uuid, hide_value=True))
    o.extend(label_stub(tp2_pin_x, 199, "P5_LOGIC_USB", "right", 12, 1.0))
    o.append(text_block("TP2", tp2_x + 4, 196, 1.0))

    # Unused channels C/D: /OE high disables, A inputs defined low, Y outputs NC.
    u1c_x, u1d_x, unused_y = 230, 305, 210
    o.append(instance("RenStd:AHCT125_CH3", "U1C", "SN74AHCT125N unused", u1c_x, unused_y, ["10","9","8"],
                      description="Unused AHCT125 channel 3 disabled", project_uuid=root_uuid, hide_value=True))
    o.append(instance("RenStd:AHCT125_CH4", "U1D", "SN74AHCT125N unused", u1d_x, unused_y, ["13","12","11"],
                      description="Unused AHCT125 channel 4 disabled", project_uuid=root_uuid, hide_value=True))
    for x, oe_pin, a_pin, y_pin in [(u1c_x, "10", "9", "8"), (u1d_x, "13", "12", "11")]:
        o.extend(label_stub(x-20.32, unused_y, "GND_COMMON", "left", 14, 1.05))
        o.extend(label_stub(x, unused_y-15.24, "P5_LOGIC_USB", "up", 13, 1.05))
        o.append(no_connect(x+20.32, unused_y))
        o.extend(text_lines([
            f"/{'OE3' if oe_pin == '10' else 'OE4'} high = disabled",
            f"A pin {a_pin} tied low; Y pin {y_pin} NC"
        ], x-20, unused_y+21, 0.9, False, 3.2))

    # 12 V high-current path. Uses RP1, not the rejected 1N5822 diode.
    o.append(text_block("12 V POWER INPUT / PROTECTION — HIGH CURRENT OFF-BREADBOARD", 18, 241, 1.55, True))
    o.extend(text_lines([
        "F1 is off-board inline before J3.",
        "RP1 = verified high-current reverse-polarity block; no 1N5822 in the full-current path."
    ], 18, 249, 1.0, False, 3.1))
    power_y = 266
    o.append(instance("RenStd:CONN_2_RIGHT", "J3", "12V IN", 42, power_y+2.54, ["1","2"],
                      footprint="TerminalBlock:TerminalBlock_bornier-2_P5.08mm", description="12 V/GND input from fused supply", project_uuid=root_uuid))
    o.append(instance("RenStd:FUSE", "F1", "7.5A blade off-board", 92, power_y, ["1","2"], description="Source-side DC fuse; off board", project_uuid=root_uuid))
    o.append(instance("RenStd:REV_PROT", "RP1", "high-current reverse protection", 150, power_y, ["1","2"], description="MOSFET ideal-diode or rated module above fuse current", project_uuid=root_uuid))
    # J3 pins on right at x+13.97, y +/- 2.54. Top + goes to fused net; bottom GND uses label.
    j3x = 42 + 13.97
    o.extend(label_stub(j3x, power_y, "P12_IN_FUSED", "right", 12, 1.05))
    # F1 is off-board ahead of J3: F1 pin 2, J3 pin 1, and RP1 pin 1 are all P12_IN_FUSED.
    o.extend(label_stub(92-8.89, power_y, "P12_PSU_PLUS", "left", 12, 1.0))
    o.extend(label_stub(92+8.89, power_y, "P12_IN_FUSED", "right", 12, 1.0))
    o.extend(label_stub(150-15.24, power_y, "P12_IN_FUSED", "left", 12, 1.0))
    o.extend(label_stub(150+15.24, power_y, "P12_PROTECTED", "right", 15, 1.1))
    o.extend(label_stub(j3x, power_y+5.08, "GND_COMMON", "right", 12, 1.05))

    # Bulk cap, 12 V power LED, and TP1.
    o.append(instance("RenStd:C_POL", "C1", "1000µF / 25V", 215, power_y, ["1","2"], description="12 V bulk smoothing capacitor", project_uuid=root_uuid))
    o.extend(label_stub(215, power_y-7.62, "P12_PROTECTED", "right", 13, 1.05))
    o.extend(label_stub(215, power_y+7.62, "GND_COMMON", "right", 13, 1.05))
    tp1_x = 244
    tp1_pin_x = tp1_x - 1.27
    o.append(instance("RenStd:TP", "TP1", "P12_PROTECTED", tp1_x, power_y-12, ["1"], description="12 V protected rail test point", project_uuid=root_uuid, hide_value=True))
    o.extend(label_stub(tp1_pin_x, power_y-12, "P12_PROTECTED", "right", 13, 1.0))
    o.append(text_block("TP1", tp1_x + 4, power_y-16, 1.0))

    # 12 V power-good LED is drawn above the title block area so nothing collides with the sheet metadata.
    power_led_y = 158
    o.append(text_block("12 V POWER-GOOD LED", 220, 142, 1.25, True))
    o.append(instance("RenStd:R_US", "R4", "1kΩ 1/4W", 250, power_led_y, ["1","2"], description="12 V power-good LED resistor", project_uuid=root_uuid))
    o.append(instance("RenStd:LED", "LED2", "green power", 295, power_led_y, ["1","2"], description="12 V power-good LED", project_uuid=root_uuid))
    o.extend(label_stub(250-8.89, power_led_y, "P12_PROTECTED", "left", 13, 1.05))
    o.append(wire(250+8.89, power_led_y, 295-8.89, power_led_y))
    o.append(label("LED2_SERIES", 266, power_led_y, 0, "left bottom", 0.95))
    o.extend(label_stub(295+8.89, power_led_y, "GND_COMMON", "right", 14, 1.05))

    o.extend(text_lines([
        "Pre-power: P12_PROTECTED↔P5_LOGIC_USB open/megaohms.",
        "Common GND only; never feed ESP32 VIN from 12 V."
    ], 18, 283, 0.92, True, 3.0))

    sch = f'''(kicad_sch
  (version 20260101)
  (generator "ren-generate-kicad-standard-schematic")
  (generator_version "2.0")
  (uuid {q(root_uuid)})
  (paper "A3")
  (title_block
    (title "ESP32 LED Controller v6 — Reviewed Standard Schematic")
    (date "2026-05-20")
    (rev "v6-kicad-standard-2")
    (company "Lisbon AV installation")
    (comment 1 "U1 is SN74AHCT125N shown as U1A/U1B/U1C/U1D/U1P; net names match audited JSON netlist")
    (comment 2 "RP1 high-current reverse-polarity protection replaces rejected 1N5822 full-current path")
  )
  (lib_symbols
    {lib_symbols()}
  )
  {' '.join(o)}
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
