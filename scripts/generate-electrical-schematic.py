#!/usr/bin/env python3
"""Generate a conventional schematic-style drawing for the ESP32 LED controller.

This intentionally avoids the previous rounded-box / infographic style.  It is a
bench-readable, symbol-first schematic generated from the audited v6 circuit:
- standard-ish resistor/capacitor/diode/LED/fuse/connector symbols
- explicit SN74AHCT125 channel symbols and DIP pin numbers
- net labels rather than decorative colored rails

It is not a KiCad ERC file; it is a clean print/reference drawing.
"""
from __future__ import annotations

from pathlib import Path
import html
import math

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "diagrams"
OUT.mkdir(parents=True, exist_ok=True)
SVG_PATH = OUT / "esp32-led-controller-v6-electrical-schematic.svg"
PNG_PATH = OUT / "esp32-led-controller-v6-electrical-schematic.png"

W, H = 3400, 2600
INK = "#111111"
MUTED = "#555555"
BLUE = "#0f4c81"
RED = "#9b1c1c"
GREEN = "#0b6b3a"
AMBER = "#8a4b00"
BG = "#ffffff"

try:
    from PIL import Image, ImageDraw, ImageFont
except Exception:  # pragma: no cover
    Image = ImageDraw = ImageFont = None


class Schematic:
    def __init__(self) -> None:
        self.svg: list[str] = []
        self.svg.append(
            f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}">'
        )
        self.svg.append(f'<rect width="100%" height="100%" fill="{BG}"/>')
        self.svg.append(
            '<defs>'
            '<marker id="arrow" markerWidth="12" markerHeight="12" refX="10" refY="6" orient="auto">'
            '<path d="M0,0 L12,6 L0,12 z" fill="#111111"/></marker>'
            '</defs>'
        )
        self.img = None
        self.draw = None
        self.fonts = {}
        if Image is not None:
            self.img = Image.new("RGB", (W, H), BG)
            self.draw = ImageDraw.Draw(self.img)
            font_paths = [
                "/System/Library/Fonts/Supplemental/Arial.ttf",
                "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
                "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
                "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
            ]
            regular = next((p for p in font_paths if Path(p).exists() and "Bold" not in p), None)
            bold = next((p for p in font_paths if Path(p).exists() and "Bold" in p), regular)
            for size in [18, 20, 22, 24, 26, 30, 34, 40, 48, 56]:
                try:
                    self.fonts[(size, False)] = ImageFont.truetype(regular, size) if regular else ImageFont.load_default()
                    self.fonts[(size, True)] = ImageFont.truetype(bold, size) if bold else ImageFont.load_default()
                except Exception:
                    self.fonts[(size, False)] = ImageFont.load_default()
                    self.fonts[(size, True)] = ImageFont.load_default()

    def finish(self) -> None:
        self.svg.append("</svg>")
        SVG_PATH.write_text("\n".join(self.svg), encoding="utf-8")
        if self.img is not None:
            self.img.save(PNG_PATH)

    def esc(self, s: str) -> str:
        return html.escape(str(s), quote=True)

    def color(self, c: str | None) -> str:
        return c or INK

    def line(self, x1, y1, x2, y2, c=INK, w=4, dash: str | None = None, arrow=False) -> None:
        dash_attr = f' stroke-dasharray="{dash}"' if dash else ""
        arrow_attr = ' marker-end="url(#arrow)"' if arrow else ""
        self.svg.append(
            f'<line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" stroke="{c}" stroke-width="{w}" stroke-linecap="round" fill="none"{dash_attr}{arrow_attr}/>'
        )
        if self.draw is not None:
            self.draw.line((x1, y1, x2, y2), fill=c, width=w)

    def polyline(self, pts, c=INK, w=4, dash: str | None = None) -> None:
        pstr = " ".join(f"{x},{y}" for x, y in pts)
        dash_attr = f' stroke-dasharray="{dash}"' if dash else ""
        self.svg.append(
            f'<polyline points="{pstr}" stroke="{c}" stroke-width="{w}" stroke-linecap="round" stroke-linejoin="round" fill="none"{dash_attr}/>'
        )
        if self.draw is not None:
            self.draw.line(pts, fill=c, width=w, joint="curve")

    def rect(self, x, y, w, h, c=INK, fill=BG, sw=3) -> None:
        self.svg.append(
            f'<rect x="{x}" y="{y}" width="{w}" height="{h}" fill="{fill}" stroke="{c}" stroke-width="{sw}"/>'
        )
        if self.draw is not None:
            self.draw.rectangle((x, y, x + w, y + h), outline=c, fill=fill, width=sw)

    def circle(self, x, y, r=8, c=INK, fill=INK, sw=3) -> None:
        self.svg.append(
            f'<circle cx="{x}" cy="{y}" r="{r}" fill="{fill}" stroke="{c}" stroke-width="{sw}"/>'
        )
        if self.draw is not None:
            self.draw.ellipse((x - r, y - r, x + r, y + r), outline=c, fill=fill, width=sw)

    def polygon(self, pts, c=INK, fill=BG, sw=4) -> None:
        pstr = " ".join(f"{x},{y}" for x, y in pts)
        self.svg.append(
            f'<polygon points="{pstr}" fill="{fill}" stroke="{c}" stroke-width="{sw}" stroke-linejoin="round"/>'
        )
        if self.draw is not None:
            self.draw.polygon(pts, outline=c, fill=fill)
            # PIL polygon outline width workaround: draw edge lines
            self.draw.line(pts + [pts[0]], fill=c, width=sw, joint="curve")

    def text(self, x, y, s, size=24, bold=False, c=INK, anchor="start", valign="baseline") -> None:
        lines = str(s).split("\n")
        weight = "700" if bold else "400"
        dominant = "middle" if valign == "middle" else "auto"
        if len(lines) == 1:
            self.svg.append(
                f'<text x="{x}" y="{y}" fill="{c}" font-family="Arial, Helvetica, sans-serif" font-size="{size}" font-weight="{weight}" text-anchor="{anchor}" dominant-baseline="{dominant}">{self.esc(lines[0])}</text>'
            )
        else:
            self.svg.append(
                f'<text x="{x}" y="{y}" fill="{c}" font-family="Arial, Helvetica, sans-serif" font-size="{size}" font-weight="{weight}" text-anchor="{anchor}">'
            )
            for i, line in enumerate(lines):
                dy = 0 if i == 0 else int(size * 1.25)
                self.svg.append(f'<tspan x="{x}" dy="{dy}">{self.esc(line)}</tspan>')
            self.svg.append("</text>")
        if self.draw is not None:
            font = self.fonts.get((size, bold)) or next(iter(self.fonts.values()))
            yy = y
            for i, line in enumerate(lines):
                bbox = self.draw.textbbox((0, 0), line, font=font)
                tw = bbox[2] - bbox[0]
                th = bbox[3] - bbox[1]
                xx = x
                if anchor == "middle":
                    xx = x - tw / 2
                elif anchor == "end":
                    xx = x - tw
                ydraw = yy
                if valign == "middle":
                    ydraw = yy - th / 2
                self.draw.text((xx, ydraw), line, font=font, fill=c)
                yy += int(size * 1.25)

    def junction(self, x, y) -> None:
        self.circle(x, y, 9, c=INK, fill=INK, sw=2)

    def net_label(self, x, y, label, c=INK, left=False) -> None:
        # small schematic net flag, no rounded/blobby UI styling
        w = max(150, 14 * len(label) + 34)
        h = 38
        if left:
            pts = [(x, y), (x + 20, y - h / 2), (x + w, y - h / 2), (x + w, y + h / 2), (x + 20, y + h / 2)]
            tx = x + 28
            anchor = "start"
        else:
            pts = [(x, y), (x - 20, y - h / 2), (x - w, y - h / 2), (x - w, y + h / 2), (x - 20, y + h / 2)]
            tx = x - w + 12
            anchor = "start"
        self.polygon(pts, c=c, fill="#ffffff", sw=3)
        self.text(tx, y + 8, label, size=20, bold=True, c=c, anchor=anchor)

    def ground(self, x, y, label: str | None = None) -> None:
        self.line(x, y, x, y + 18, INK, 4)
        self.line(x - 34, y + 18, x + 34, y + 18, INK, 4)
        self.line(x - 24, y + 31, x + 24, y + 31, INK, 4)
        self.line(x - 12, y + 44, x + 12, y + 44, INK, 4)
        if label:
            self.text(x + 46, y + 36, label, size=20, c=MUTED, valign="middle")

    def nc(self, x, y, label="NC") -> None:
        self.line(x - 16, y - 16, x + 16, y + 16, INK, 3)
        self.line(x - 16, y + 16, x + 16, y - 16, INK, 3)
        self.text(x + 28, y + 8, label, size=20, c=MUTED)

    def resistor_h(self, x1, y, x2, label, value, c=INK) -> None:
        lead = 40
        self.line(x1, y, x1 + lead, y, c, 4)
        self.line(x2 - lead, y, x2, y, c, 4)
        start = x1 + lead
        end = x2 - lead
        n = 6
        amp = 26
        pts = [(start, y)]
        step = (end - start) / (n * 2)
        for i in range(n * 2 - 1):
            x = start + step * (i + 1)
            yy = y - amp if i % 2 == 0 else y + amp
            pts.append((x, yy))
        pts.append((end, y))
        self.polyline(pts, c, 4)
        self.text((x1 + x2) / 2, y - 52, label, size=22, bold=True, c=c, anchor="middle")
        self.text((x1 + x2) / 2, y + 70, value, size=20, c=MUTED, anchor="middle")

    def resistor_v(self, x, y1, y2, label, value, c=INK) -> None:
        lead = 35
        self.line(x, y1, x, y1 + lead, c, 4)
        self.line(x, y2 - lead, x, y2, c, 4)
        start = y1 + lead
        end = y2 - lead
        n = 6
        amp = 24
        pts = [(x, start)]
        step = (end - start) / (n * 2)
        for i in range(n * 2 - 1):
            y = start + step * (i + 1)
            xx = x - amp if i % 2 == 0 else x + amp
            pts.append((xx, y))
        pts.append((x, end))
        self.polyline(pts, c, 4)
        self.text(x + 58, (y1 + y2) / 2 - 12, label, size=22, bold=True, c=c, valign="middle")
        self.text(x + 58, (y1 + y2) / 2 + 22, value, size=20, c=MUTED, valign="middle")

    def capacitor_v(self, x, y_top, y_bot, label, value, polarized=False) -> None:
        mid = (y_top + y_bot) / 2
        self.line(x, y_top, x, mid - 35, INK, 4)
        self.line(x - 42, mid - 35, x + 42, mid - 35, INK, 5)
        self.line(x - 42, mid + 35, x + 42, mid + 35, INK, 5)
        self.line(x, mid + 35, x, y_bot, INK, 4)
        if polarized:
            self.text(x + 52, mid - 48, "+", size=34, bold=True)
        self.text(x + 70, mid - 12, label, size=22, bold=True, valign="middle")
        self.text(x + 70, mid + 24, value, size=20, c=MUTED, valign="middle")

    def diode_h(self, x1, y, x2, label, value, schottky=False) -> None:
        # anode left, cathode right
        mid = (x1 + x2) / 2
        tri_l = mid - 42
        tri_r = mid + 20
        self.line(x1, y, tri_l, y, INK, 4)
        self.polygon([(tri_l, y - 42), (tri_l, y + 42), (tri_r, y)], c=INK, fill=BG, sw=4)
        self.line(tri_r + 5, y - 50, tri_r + 5, y + 50, INK, 5)
        if schottky:
            self.line(tri_r + 5, y - 50, tri_r + 22, y - 34, INK, 4)
            self.line(tri_r + 5, y + 50, tri_r - 12, y + 34, INK, 4)
        self.line(tri_r + 5, y, x2, y, INK, 4)
        self.text(mid, y - 70, label, size=22, bold=True, anchor="middle")
        self.text(mid, y + 86, value, size=20, c=MUTED, anchor="middle")

    def fuse_h(self, x1, y, x2, label, value) -> None:
        self.line(x1, y, x1 + 44, y, INK, 4)
        self.rect(x1 + 44, y - 34, x2 - x1 - 88, 68, c=INK, fill=BG, sw=4)
        # fuse link
        self.polyline([(x1 + 66, y), (x1 + 110, y - 20), (x1 + 154, y + 20), (x1 + 198, y)], INK, 4)
        self.line(x2 - 44, y, x2, y, INK, 4)
        self.text((x1 + x2) / 2, y - 62, label, size=22, bold=True, anchor="middle")
        self.text((x1 + x2) / 2, y + 72, value, size=20, c=MUTED, anchor="middle")

    def led_v_to_gnd(self, x, y_top, y_bot, r_label, r_value, led_label) -> None:
        self.resistor_v(x, y_top, y_top + 150, r_label, r_value)
        y = y_top + 230
        self.line(x, y_top + 150, x, y - 54, INK, 4)
        self.polygon([(x - 36, y - 54), (x + 36, y - 54), (x, y + 18)], c=INK, fill=BG, sw=4)
        self.line(x - 42, y + 24, x + 42, y + 24, INK, 5)
        # LED arrows
        self.line(x + 50, y - 42, x + 92, y - 78, INK, 3, arrow=True)
        self.line(x + 64, y - 10, x + 106, y - 46, INK, 3, arrow=True)
        self.line(x, y + 24, x, y_bot, INK, 4)
        self.text(x + 70, y - 15, led_label, size=20, bold=True, valign="middle")

    def connector(self, x, y, ref, rows, pin_spacing=78) -> dict[str, tuple[int, int]]:
        # x,y is upper-left of connector body. Pins exit left.
        h = 70 + pin_spacing * (len(rows) - 1)
        self.rect(x, y, 300, h, c=INK, fill=BG, sw=4)
        self.text(x + 150, y - 22, ref, size=24, bold=True, anchor="middle")
        pts = {}
        for i, (pin, name) in enumerate(rows):
            py = y + 35 + i * pin_spacing
            self.circle(x + 26, py, 8, c=INK, fill=BG, sw=4)
            self.line(x - 80, py, x + 18, py, INK, 4)
            self.text(x + 54, py + 8, f"{pin}  {name}", size=22, bold=(pin == "1"))
            pts[name] = (x - 80, py)
        return pts

    def mcu(self, x, y) -> dict[str, tuple[int, int]]:
        self.rect(x, y, 460, 620, c=INK, fill=BG, sw=4)
        self.text(x + 230, y + 45, "ESP32 DevKit V1", size=30, bold=True, anchor="middle")
        self.text(x + 230, y + 88, "USB-C powered only", size=22, c=MUTED, anchor="middle")
        pins = {
            "VIN/5V": y + 150,
            "GND": y + 230,
            "GPIO25": y + 330,
            "GPIO26": y + 430,
            "GPIO27": y + 530,
        }
        out = {}
        for name, py in pins.items():
            self.line(x + 460, py, x + 540, py, INK, 4)
            self.circle(x + 460, py, 7, c=INK, fill=BG, sw=3)
            self.text(x + 300, py + 8, name, size=22, bold=True)
            out[name] = (x + 540, py)
        return out

    def buffer(self, x, y, unit, in_pin, out_pin, oe_pin, oe_to="GND", unused=False) -> dict[str, tuple[int, int]]:
        # non-inverting tri-state buffer, left-to-right. x,y center.
        self.polygon([(x - 90, y - 60), (x - 90, y + 60), (x + 60, y)], c=INK, fill=BG, sw=4)
        self.text(x - 15, y + 10, unit, size=22, bold=True, anchor="middle", valign="middle")
        self.text(x - 132, y - 16, f"{in_pin}", size=18, c=MUTED, anchor="end")
        self.text(x + 82, y - 16, f"{out_pin}", size=18, c=MUTED)
        self.line(x - 160, y, x - 90, y, INK, 4)
        self.line(x + 60, y, x + 145, y, INK, 4)
        # active-low OE control pin shown at bottom of triangle
        self.line(x - 10, y + 108, x - 10, y + 48, INK, 4)
        self.text(x + 8, y + 104, f"/{oe_pin}", size=18, c=MUTED)
        if oe_to == "GND":
            self.ground(x - 10, y + 108, "LOW = enabled")
        elif oe_to == "+5V":
            self.line(x - 10, y + 108, x - 10, y + 150, INK, 4)
            self.net_label(x - 10, y + 150, "+5V_LOGIC", c=BLUE, left=False)
            self.text(x + 70, y + 150, "HIGH = disabled", size=18, c=MUTED, valign="middle")
        if unused:
            self.text(x - 10, y - 78, "unused channel", size=18, c=MUTED, anchor="middle")
        return {"in": (x - 160, y), "out": (x + 145, y), "oe": (x - 10, y + 108)}


def draw_sheet() -> Schematic:
    s = Schematic()

    # Title block
    s.text(90, 70, "ESP32 LED Controller v6 — Electrical Schematic", size=48, bold=True)
    s.text(90, 118, "Conventional symbol view; net names and AHCT125N pin numbers are the source of truth.", size=24, c=MUTED)
    s.text(90, 155, "Critical: U1 pins 10 and 13 are /OE3 and /OE4. Tie them to +5V_LOGIC to disable unused channels.", size=26, bold=True, c=RED)
    s.line(80, 185, W - 80, 185, INK, 3)

    # 12V input and protection
    s.connector(110, 280, "J3  12V IN", [("1", "+12V_IN"), ("2", "GND")], pin_spacing=105)
    j3_p = (110 - 80, 280 + 35)
    j3_g = (110 - 80, 280 + 35 + 105)
    p12_y = 315
    gnd_y = 420
    # connector external pin leads align from left; route from right-side symbol pin ends
    s.line(330, p12_y, 430, p12_y, INK, 4)
    s.fuse_h(430, p12_y, 710, "F1", "7.5 A blade, off-board")
    s.diode_h(760, p12_y, 1010, "D1 / RP1", "1N5822 only for current-limited proto", schottky=True)
    s.line(1010, p12_y, 3030, p12_y, INK, 4)
    s.net_label(1115, p12_y, "+12V_PROTECTED", c=RED, left=True)
    s.line(330, gnd_y, 3030, gnd_y, INK, 4)
    s.net_label(1120, gnd_y, "GND_COMMON", c=INK, left=True)
    s.junction(330, p12_y)
    s.junction(330, gnd_y)

    # C1, power LED
    s.line(1250, p12_y, 1250, 520, INK, 4)
    s.capacitor_v(1250, 520, 740, "C1", "1000µF / 25V", polarized=True)
    s.line(1250, 740, 1250, gnd_y, INK, 4)
    s.junction(1250, p12_y)
    s.junction(1250, gnd_y)

    s.line(1510, p12_y, 1510, 540, INK, 4)
    s.led_v_to_gnd(1510, 540, 790, "R4", "1k", "LED2 green")
    s.line(1510, 790, 1510, gnd_y, INK, 4)
    s.junction(1510, p12_y)
    s.junction(1510, gnd_y)

    # ESP32 and logic ground/power
    esp = s.mcu(560, 770)
    vin = esp["VIN/5V"]
    egnd = esp["GND"]
    g25 = esp["GPIO25"]
    g26 = esp["GPIO26"]
    g27 = esp["GPIO27"]

    s.net_label(vin[0] + 70, vin[1], "+5V_LOGIC", c=BLUE, left=True)
    s.text(vin[0] + 70, vin[1] + 52, "from ESP32 USB/VIN only — do not backfeed", size=19, c=RED)
    s.line(vin[0], vin[1], vin[0] + 70, vin[1], INK, 4)
    s.line(egnd[0], egnd[1], egnd[0] + 60, egnd[1], INK, 4)
    s.ground(egnd[0] + 60, egnd[1], "to GND_COMMON")

    # Common ground reference jumper from power bus to logic ground, shown explicitly
    s.polyline([(1680, gnd_y), (1680, 705), (1120, 705), (1120, 1000)], INK, 4, dash="10 10")
    s.text(1710, 675, "single low-current common-ground reference", size=20, c=MUTED)
    s.ground(1120, 1000)

    # Status LED from GPIO27
    s.polyline([(g27[0], g27[1]), (480, g27[1]), (480, 1530)], INK, 4)
    s.resistor_v(480, 1530, 1690, "R3", "220Ω")
    # LED1 symbol below R3
    led_y = 1765
    s.line(480, 1690, 480, led_y - 55, INK, 4)
    s.polygon([(444, led_y - 55), (516, led_y - 55), (480, led_y + 15)], c=INK, fill=BG, sw=4)
    s.line(438, led_y + 22, 522, led_y + 22, INK, 5)
    s.line(530, led_y - 45, 570, led_y - 82, INK, 3, arrow=True)
    s.line(544, led_y - 12, 584, led_y - 50, INK, 3, arrow=True)
    s.text(565, led_y, "LED1 red\nstatus", size=20, bold=True, valign="middle")
    s.line(480, led_y + 22, 480, 1900, INK, 4)
    s.ground(480, 1900)

    # AHCT125 used buffers
    a = s.buffer(1580, 1100, "U1A", "2  1A", "3  1Y", "OE1 pin 1", oe_to="GND")
    b = s.buffer(1580, 1370, "U1B", "5  2A", "6  2Y", "OE2 pin 4", oe_to="GND")

    # ESP32 GPIO to inputs
    s.polyline([g25, (1320, g25[1]), (1320, a["in"][1]), a["in"]], INK, 4)
    s.text(1265, a["in"][1] - 22, "GPIO25", size=20, c=MUTED, anchor="end")
    s.polyline([g26, (1280, g26[1]), (1280, b["in"][1]), b["in"]], INK, 4)
    s.text(1265, b["in"][1] - 22, "GPIO26", size=20, c=MUTED, anchor="end")

    # Data resistors and outputs toward connectors
    s.resistor_h(a["out"][0], a["out"][1], 2170, "R1", "470Ω")
    s.resistor_h(b["out"][0], b["out"][1], 2170, "R2", "470Ω")
    s.net_label(2220, a["out"][1], "J1_DATA", c=GREEN, left=True)
    s.net_label(2220, b["out"][1], "J2_DATA", c=GREEN, left=True)

    # U1 power and decoupling
    s.rect(1975, 650, 410, 230, c=INK, fill=BG, sw=4)
    s.text(2180, 690, "U1 power", size=24, bold=True, anchor="middle")
    s.text(2010, 745, "pin 14 VCC", size=22, bold=True)
    s.text(2010, 820, "pin 7 GND", size=22, bold=True)
    s.line(2385, 740, 2480, 740, INK, 4)
    s.net_label(2480, 740, "+5V_LOGIC", c=BLUE, left=True)
    s.line(2385, 815, 2480, 815, INK, 4)
    s.ground(2480, 815)
    s.capacitor_v(2650, 650, 820, "C2", "0.1µF")
    s.capacitor_v(2820, 650, 820, "C3", "10µF")
    s.line(2650, 650, 2820, 650, INK, 4)
    s.line(2650, 820, 2820, 820, INK, 4)
    s.net_label(2650, 650, "+5V_LOGIC", c=BLUE, left=False)
    s.ground(2820, 820, "decouple at U1")

    # Unused channels disabled
    s.text(1180, 1570, "Unused AHCT125 channels — disabled, inputs defined", size=26, bold=True)
    c = s.buffer(1580, 1680, "U1C", "9  3A", "8  3Y", "OE3 pin 10", oe_to="+5V", unused=True)
    d = s.buffer(1580, 1940, "U1D", "12  4A", "11  4Y", "OE4 pin 13", oe_to="+5V", unused=True)
    # inputs to ground
    s.line(c["in"][0], c["in"][1], c["in"][0] - 80, c["in"][1], INK, 4)
    s.ground(c["in"][0] - 80, c["in"][1])
    s.text(c["in"][0] - 116, c["in"][1] - 24, "3A low", size=18, c=MUTED, anchor="end")
    s.line(d["in"][0], d["in"][1], d["in"][0] - 80, d["in"][1], INK, 4)
    s.ground(d["in"][0] - 80, d["in"][1])
    s.text(d["in"][0] - 116, d["in"][1] - 24, "4A low", size=18, c=MUTED, anchor="end")
    # outputs NC
    s.nc(c["out"][0] + 35, c["out"][1], "pin 8 NC")
    s.nc(d["out"][0] + 35, d["out"][1], "pin 11 NC")

    # LED output connectors
    j1 = s.connector(2890, 870, "J1  LED OUT", [("1", "V+"), ("2", "GND"), ("3", "DATA")], pin_spacing=78)
    j2 = s.connector(2890, 1245, "J2  LED OUT", [("1", "V+"), ("2", "GND"), ("3", "DATA")], pin_spacing=78)
    # connector pin points are left ends of little lead lines
    j1_v = j1["V+"]
    j1_g = j1["GND"]
    j1_d = j1["DATA"]
    j2_v = j2["V+"]
    j2_g = j2["GND"]
    j2_d = j2["DATA"]

    # route V+ drops from top rail to connector pins
    for pt, label_y in [(j1_v, j1_v[1]), (j2_v, j2_v[1])]:
        s.polyline([(pt[0] - 90, p12_y), (pt[0] - 90, pt[1]), pt], INK, 4)
        s.junction(pt[0] - 90, p12_y)
    # route GND from common rail
    for pt in [j1_g, j2_g]:
        s.polyline([(pt[0] - 140, gnd_y), (pt[0] - 140, pt[1]), pt], INK, 4)
        s.junction(pt[0] - 140, gnd_y)
    # route data from net labels through clean orthogonal lines to data pins
    s.polyline([(2220, a["out"][1]), (2500, a["out"][1]), (2500, j1_d[1]), j1_d], INK, 4)
    s.polyline([(2220, b["out"][1]), (2460, b["out"][1]), (2460, j2_d[1]), j2_d], INK, 4)

    # Stop/bench notes box
    s.rect(80, 2325, 3250, 190, c=INK, fill=BG, sw=3)
    s.text(110, 2365, "Bench notes / stop conditions", size=26, bold=True)
    s.text(110, 2405, "• +12V_PROTECTED and +5V_LOGIC must be open/megaohms before power.  • ESP32 is USB-powered only; never backfeed VIN from 12V supply.", size=22)
    s.text(110, 2440, "• Full LED current stays off solderless breadboard. Breadboard may carry logic/data/common-reference ground only, unless tiny current-limited LED load.", size=22)
    s.text(110, 2475, "• D1 1N5822 drawing is for the current-limited prototype path; final multi-amp protection needs a properly rated reverse-protection block.", size=22, c=RED)

    # Title block / version
    s.text(W - 90, H - 40, "projects/lisbon-av-install • esp32-led-controller-v6-electrical-schematic", size=18, c=MUTED, anchor="end")

    return s


if __name__ == "__main__":
    sheet = draw_sheet()
    sheet.finish()
    print(SVG_PATH)
    print(PNG_PATH)
