#!/usr/bin/env python3
"""Generate a physical DIP-14 pin-location schematic for the ESP32 LED controller.

This sheet is for bench wiring: U1 is drawn as the actual 14-pin DIP top view
(notch up), with pins 1-7 down the left side and pins 14-8 down the right side.
Every U1 pin has its net shown. Supporting power/data circuitry is drawn around
it with schematic symbols/net labels.
"""
from __future__ import annotations

from pathlib import Path
import html

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "diagrams"
OUT.mkdir(parents=True, exist_ok=True)
SVG_PATH = OUT / "esp32-led-controller-v6-dip14-pin-location-schematic.svg"
PNG_PATH = OUT / "esp32-led-controller-v6-dip14-pin-location-schematic.png"

W, H = 3300, 2350
INK = "#111111"
MUTED = "#555555"
RED = "#9b1c1c"
BLUE = "#0f4c81"
GREEN = "#0b6b3a"
BG = "#ffffff"

try:
    from PIL import Image, ImageDraw, ImageFont
except Exception:  # pragma: no cover
    Image = ImageDraw = ImageFont = None


class Draw:
    def __init__(self) -> None:
        self.svg = [
            f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}">',
            f'<rect width="100%" height="100%" fill="{BG}"/>',
            '<defs><marker id="arrow" markerWidth="10" markerHeight="10" refX="9" refY="5" orient="auto"><path d="M0,0 L10,5 L0,10 z" fill="#111111"/></marker></defs>',
        ]
        self.img = None
        self.draw = None
        self.fonts = {}
        if Image is not None:
            self.img = Image.new("RGB", (W, H), BG)
            self.draw = ImageDraw.Draw(self.img)
            regulars = [
                "/System/Library/Fonts/Supplemental/Arial.ttf",
                "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
            ]
            bolds = [
                "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
                "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
            ]
            reg = next((p for p in regulars if Path(p).exists()), None)
            bold = next((p for p in bolds if Path(p).exists()), reg)
            for size in [16, 18, 20, 22, 24, 26, 30, 34, 40, 46, 54]:
                try:
                    self.fonts[(size, False)] = ImageFont.truetype(reg, size) if reg else ImageFont.load_default()
                    self.fonts[(size, True)] = ImageFont.truetype(bold, size) if bold else ImageFont.load_default()
                except Exception:
                    self.fonts[(size, False)] = ImageFont.load_default()
                    self.fonts[(size, True)] = ImageFont.load_default()

    def esc(self, s: str) -> str:
        return html.escape(str(s), quote=True)

    def line(self, x1, y1, x2, y2, c=INK, w=4, dash=None, arrow=False):
        dash_attr = f' stroke-dasharray="{dash}"' if dash else ""
        arrow_attr = ' marker-end="url(#arrow)"' if arrow else ""
        self.svg.append(f'<line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" stroke="{c}" stroke-width="{w}" stroke-linecap="round" fill="none"{dash_attr}{arrow_attr}/>')
        if self.draw:
            self.draw.line((x1, y1, x2, y2), fill=c, width=w)

    def polyline(self, pts, c=INK, w=4, dash=None):
        p = " ".join(f"{x},{y}" for x, y in pts)
        dash_attr = f' stroke-dasharray="{dash}"' if dash else ""
        self.svg.append(f'<polyline points="{p}" stroke="{c}" stroke-width="{w}" stroke-linecap="round" stroke-linejoin="round" fill="none"{dash_attr}/>')
        if self.draw:
            self.draw.line(pts, fill=c, width=w, joint="curve")

    def rect(self, x, y, w, h, c=INK, fill=BG, sw=4):
        self.svg.append(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" fill="{fill}" stroke="{c}" stroke-width="{sw}"/>')
        if self.draw:
            self.draw.rectangle((x, y, x+w, y+h), outline=c, fill=fill, width=sw)

    def circle(self, x, y, r=8, c=INK, fill=BG, sw=4):
        self.svg.append(f'<circle cx="{x}" cy="{y}" r="{r}" fill="{fill}" stroke="{c}" stroke-width="{sw}"/>')
        if self.draw:
            self.draw.ellipse((x-r, y-r, x+r, y+r), outline=c, fill=fill, width=sw)

    def arc_notch(self, cx, cy, r=52):
        # SVG arc; PIL outline approximation by ellipse upper half is enough.
        self.svg.append(f'<path d="M {cx-r} {cy} A {r} {r} 0 0 0 {cx+r} {cy}" fill="none" stroke="{INK}" stroke-width="4"/>')
        if self.draw:
            self.draw.arc((cx-r, cy-r, cx+r, cy+r), start=180, end=360, fill=INK, width=4)

    def polygon(self, pts, c=INK, fill=BG, sw=4):
        p = " ".join(f"{x},{y}" for x, y in pts)
        self.svg.append(f'<polygon points="{p}" fill="{fill}" stroke="{c}" stroke-width="{sw}"/>')
        if self.draw:
            self.draw.polygon(pts, outline=c, fill=fill)
            self.draw.line(pts + [pts[0]], fill=c, width=sw)

    def text(self, x, y, s, size=22, bold=False, c=INK, anchor="start", valign="baseline"):
        lines = str(s).split("\n")
        weight = "700" if bold else "400"
        dominant = "middle" if valign == "middle" else "auto"
        if len(lines) == 1:
            self.svg.append(f'<text x="{x}" y="{y}" fill="{c}" font-family="Arial, Helvetica, sans-serif" font-size="{size}" font-weight="{weight}" text-anchor="{anchor}" dominant-baseline="{dominant}">{self.esc(lines[0])}</text>')
        else:
            self.svg.append(f'<text x="{x}" y="{y}" fill="{c}" font-family="Arial, Helvetica, sans-serif" font-size="{size}" font-weight="{weight}" text-anchor="{anchor}">')
            for i, line in enumerate(lines):
                dy = 0 if i == 0 else int(size * 1.25)
                self.svg.append(f'<tspan x="{x}" dy="{dy}">{self.esc(line)}</tspan>')
            self.svg.append('</text>')
        if self.draw:
            font = self.fonts.get((size, bold)) or ImageFont.load_default()
            yy = y
            for line in lines:
                bbox = self.draw.textbbox((0, 0), line, font=font)
                tw = bbox[2] - bbox[0]
                th = bbox[3] - bbox[1]
                xx = x - tw/2 if anchor == "middle" else x - tw if anchor == "end" else x
                ydraw = yy - th/2 if valign == "middle" else yy
                self.draw.text((xx, ydraw), line, fill=c, font=font)
                yy += int(size * 1.25)

    def net(self, x, y, label, c=INK, side="right"):
        w = max(150, len(label) * 14 + 34)
        h = 38
        if side == "right":
            pts = [(x, y), (x+20, y-h/2), (x+w, y-h/2), (x+w, y+h/2), (x+20, y+h/2)]
            tx = x + 30
        else:
            pts = [(x, y), (x-20, y-h/2), (x-w, y-h/2), (x-w, y+h/2), (x-20, y+h/2)]
            tx = x - w + 10
        self.polygon(pts, c=c, fill=BG, sw=3)
        self.text(tx, y+7, label, size=19, bold=True, c=c)

    def ground(self, x, y, label=None):
        self.line(x, y, x, y+18, INK, 4)
        self.line(x-32, y+18, x+32, y+18, INK, 4)
        self.line(x-22, y+31, x+22, y+31, INK, 4)
        self.line(x-11, y+44, x+11, y+44, INK, 4)
        if label:
            self.text(x+44, y+36, label, size=18, c=MUTED, valign="middle")

    def junction(self, x, y):
        self.circle(x, y, 8, c=INK, fill=INK, sw=2)

    def resistor_h(self, x1, y, x2, ref, value):
        self.line(x1, y, x1+35, y)
        self.line(x2-35, y, x2, y)
        start, end = x1+35, x2-35
        pts = [(start, y)]
        steps = 12
        amp = 22
        dx = (end-start)/steps
        for i in range(1, steps):
            pts.append((start+i*dx, y + (-amp if i % 2 else amp)))
        pts.append((end, y))
        self.polyline(pts)
        self.text((x1+x2)/2, y-44, ref, size=20, bold=True, anchor="middle")
        self.text((x1+x2)/2, y+58, value, size=18, c=MUTED, anchor="middle")

    def resistor_v(self, x, y1, y2, ref, value):
        self.line(x, y1, x, y1+30)
        self.line(x, y2-30, x, y2)
        start, end = y1+30, y2-30
        pts = [(x, start)]
        steps = 12
        amp = 20
        dy = (end-start)/steps
        for i in range(1, steps):
            pts.append((x + (-amp if i % 2 else amp), start+i*dy))
        pts.append((x, end))
        self.polyline(pts)
        self.text(x+50, (y1+y2)/2-14, ref, size=20, bold=True, valign="middle")
        self.text(x+50, (y1+y2)/2+18, value, size=18, c=MUTED, valign="middle")

    def cap_v(self, x, y1, y2, ref, value, plus=False):
        mid = (y1+y2)/2
        self.line(x, y1, x, mid-34)
        self.line(x-42, mid-34, x+42, mid-34, w=5)
        self.line(x-42, mid+34, x+42, mid+34, w=5)
        self.line(x, mid+34, x, y2)
        if plus:
            self.text(x+52, mid-44, "+", size=34, bold=True)
        self.text(x+64, mid-10, ref, size=20, bold=True, valign="middle")
        self.text(x+64, mid+22, value, size=18, c=MUTED, valign="middle")

    def diode_h(self, x1, y, x2, ref, value):
        mid = (x1+x2)/2
        left = mid-42
        right = mid+20
        self.line(x1, y, left, y)
        self.polygon([(left, y-38), (left, y+38), (right, y)], fill=BG)
        self.line(right+7, y-46, right+7, y+46, w=5)
        self.line(right+7, y-46, right+24, y-30)
        self.line(right+7, y+46, right-10, y+30)
        self.line(right+7, y, x2, y)
        self.text(mid, y-62, ref, size=20, bold=True, anchor="middle")
        self.text(mid, y+78, value, size=18, c=MUTED, anchor="middle")

    def fuse_h(self, x1, y, x2, ref, value):
        self.line(x1, y, x1+35, y)
        self.rect(x1+35, y-30, x2-x1-70, 60)
        self.polyline([(x1+55, y), (x1+95, y-18), (x1+135, y+18), (x1+175, y)])
        self.line(x2-35, y, x2, y)
        self.text((x1+x2)/2, y-52, ref, size=20, bold=True, anchor="middle")
        self.text((x1+x2)/2, y+62, value, size=18, c=MUTED, anchor="middle")

    def connector(self, x, y, title, rows, spacing=72):
        h = 56 + spacing*(len(rows)-1)
        self.rect(x, y, 280, h)
        self.text(x+140, y-22, title, size=22, bold=True, anchor="middle")
        pins = {}
        for i, (num, name) in enumerate(rows):
            py = y+28+i*spacing
            self.line(x-74, py, x, py)
            self.circle(x+24, py, 7, fill=BG)
            self.text(x+50, py+7, f"{num}  {name}", size=20, bold=True)
            pins[name] = (x-74, py)
        return pins

    def led_v(self, x, y1, y2, ref, value, label):
        self.resistor_v(x, y1, y1+145, ref, value)
        y = y1+215
        self.line(x, y1+145, x, y-45)
        self.polygon([(x-34, y-45), (x+34, y-45), (x, y+20)], fill=BG)
        self.line(x-40, y+26, x+40, y+26, w=5)
        self.line(x+48, y-35, x+88, y-70, arrow=True, w=3)
        self.line(x+60, y-4, x+100, y-40, arrow=True, w=3)
        self.text(x+64, y, label, size=18, bold=True, valign="middle")
        self.line(x, y+26, x, y2)

    def save(self):
        self.svg.append("</svg>")
        SVG_PATH.write_text("\n".join(self.svg), encoding="utf-8")
        if self.img is not None:
            self.img.save(PNG_PATH)


def main():
    d = Draw()

    # Title
    d.text(90, 70, "ESP32 LED Controller v6 — DIP-14 Pin-Location Schematic", size=46, bold=True)
    d.text(90, 118, "U1 shown as actual 74AHCT125N DIP-14 top view: notch up, pins 1–7 left side, pins 14–8 right side.", size=24, c=MUTED)
    d.text(90, 155, "This is the bench-wiring view: every IC pin location and net is explicit.", size=24, bold=True, c=RED)
    d.line(80, 185, W-80, 185, w=3)

    # Power rails / sources
    p12_y = 300
    gnd_y = 420
    p5_y = 540
    d.text(100, 245, "Power / rails", size=26, bold=True)
    j3 = d.connector(120, 295, "J3 12V IN", [("1", "+12V"), ("2", "GND")], spacing=88)
    d.line(326, p12_y+23, 410, p12_y+23)
    d.fuse_h(410, p12_y+23, 660, "F1", "7.5A off-board")
    d.diode_h(700, p12_y+23, 930, "D1/RP1", "1N5822 proto only")
    d.line(930, p12_y+23, 1240, p12_y+23)
    d.net(1240, p12_y+23, "+12V_PROTECTED", c=RED, side="right")
    d.line(326, p12_y+111, 1240, p12_y+111)
    d.net(1240, p12_y+111, "GND_COMMON", side="right")
    d.junction(326, p12_y+23)
    d.junction(326, p12_y+111)

    # C1 and green LED on 12V protected
    d.line(1070, p12_y+23, 1070, 650)
    d.cap_v(1070, 650, 825, "C1", "1000µF/25V", plus=True)
    d.ground(1070, 825)
    d.line(1195, p12_y+23, 1195, 660)
    d.led_v(1195, 660, 860, "R4", "1k", "LED2 green")
    d.ground(1195, 860)

    # ESP32 block
    esp_x, esp_y = 130, 760
    d.rect(esp_x, esp_y, 430, 510)
    d.text(esp_x+215, esp_y+42, "ESP32 DevKit V1", size=28, bold=True, anchor="middle")
    d.text(esp_x+215, esp_y+78, "USB-C powered only", size=20, c=MUTED, anchor="middle")
    esp_pins = {
        "VIN/5V": esp_y+140,
        "GND": esp_y+220,
        "GPIO25": esp_y+315,
        "GPIO26": esp_y+390,
        "GPIO27": esp_y+465,
    }
    esp_out = {}
    for name, y in esp_pins.items():
        d.text(esp_x+230, y+7, name, size=20, bold=True)
        d.line(esp_x+430, y, esp_x+520, y)
        d.circle(esp_x+430, y, 6, fill=BG, sw=3)
        esp_out[name] = (esp_x+520, y)
    d.net(esp_out["VIN/5V"][0]+10, esp_out["VIN/5V"][1], "+5V_LOGIC", c=BLUE, side="right")
    d.text(esp_out["VIN/5V"][0]+20, esp_out["VIN/5V"][1]+48, "from USB/VIN only — do not backfeed", size=18, c=RED)
    d.ground(esp_out["GND"][0]+10, esp_out["GND"][1], "GND_COMMON")

    # U1 DIP14 physical pinout
    body_x, body_y = 1250, 720
    body_w, body_h = 790, 980
    d.rect(body_x, body_y, body_w, body_h, sw=5)
    d.arc_notch(body_x + body_w/2, body_y, r=70)
    d.text(body_x+body_w/2, body_y+92, "U1  SN74AHCT125N", size=32, bold=True, anchor="middle")
    d.text(body_x+body_w/2, body_y+132, "DIP-14 top view / notch up", size=21, c=MUTED, anchor="middle")

    pitch = 116
    left_pins = [
        (1, "/OE1", "GND", "enable ch1"),
        (2, "1A", "GPIO25", "from ESP32"),
        (3, "1Y", "R1 → J1_DATA", "output ch1"),
        (4, "/OE2", "GND", "enable ch2"),
        (5, "2A", "GPIO26", "from ESP32"),
        (6, "2Y", "R2 → J2_DATA", "output ch2"),
        (7, "GND", "GND_COMMON", "logic ground"),
    ]
    right_pins = [
        (14, "VCC", "+5V_LOGIC", "U1 supply"),
        (13, "/OE4", "+5V_LOGIC", "disable ch4"),
        (12, "4A", "GND", "unused input low"),
        (11, "4Y", "NC", "unused output"),
        (10, "/OE3", "+5V_LOGIC", "disable ch3"),
        (9, "3A", "GND", "unused input low"),
        (8, "3Y", "NC", "unused output"),
    ]
    pin_y0 = body_y + 175
    lcoords = {}
    rcoords = {}
    for i, (pin, name, net, why) in enumerate(left_pins):
        y = pin_y0 + i*pitch
        d.line(body_x-105, y, body_x, y)
        d.circle(body_x, y, 7, fill=BG)
        d.text(body_x+28, y-10, f"{pin}", size=18, bold=True)
        d.text(body_x+68, y+7, name, size=22, bold=True)
        d.text(body_x+170, y+7, why, size=18, c=MUTED)
        d.text(body_x-130, y+7, net, size=20, bold=True, anchor="end", c=BLUE if "+5" in net else GREEN if "DATA" in net or "GPIO" in net else INK)
        lcoords[pin] = (body_x-105, y)
    for i, (pin, name, net, why) in enumerate(right_pins):
        y = pin_y0 + i*pitch
        d.line(body_x+body_w, y, body_x+body_w+105, y)
        d.circle(body_x+body_w, y, 7, fill=BG)
        d.text(body_x+body_w-28, y-10, f"{pin}", size=18, bold=True, anchor="end")
        d.text(body_x+body_w-145, y+7, name, size=22, bold=True, anchor="end")
        d.text(body_x+body_w-350, y+7, why, size=18, c=MUTED, anchor="end")
        d.text(body_x+body_w+130, y+7, net, size=20, bold=True, c=BLUE if "+5" in net else INK)
        rcoords[pin] = (body_x+body_w+105, y)

    # GPIO routes to physical U1 input pins
    d.polyline([esp_out["GPIO25"], (840, esp_out["GPIO25"][1]), (840, lcoords[2][1]), lcoords[2]])
    d.polyline([esp_out["GPIO26"], (795, esp_out["GPIO26"][1]), (795, lcoords[5][1]), lcoords[5]])
    # status LED
    d.polyline([esp_out["GPIO27"], (650, esp_out["GPIO27"][1]), (650, 1500)])
    d.resistor_v(650, 1500, 1645, "R3", "220Ω")
    led_y = 1715
    d.line(650, 1645, 650, led_y-45)
    d.polygon([(616, led_y-45), (684, led_y-45), (650, led_y+20)], fill=BG)
    d.line(610, led_y+26, 690, led_y+26, w=5)
    d.text(720, led_y, "LED1 red status", size=18, bold=True, valign="middle")
    d.line(650, led_y+26, 650, 1830)
    d.ground(650, 1830)

    # OE/GND/+5/NC explicit routes for U1 pins
    # Left pin 1, 4, 7 to ground symbols
    for pin in [1, 4, 7]:
        x, y = lcoords[pin]
        d.line(x, y, x-110, y)
        d.ground(x-110, y, "GND" if pin == 1 else None)
    # Right +5 pins 14,13,10 use net flags
    for pin in [14, 13, 10]:
        x, y = rcoords[pin]
        d.line(x, y, x+70, y)
        d.net(x+70, y, "+5V_LOGIC", c=BLUE, side="right")
    # Right GND pins 12,9
    for pin in [12, 9]:
        x, y = rcoords[pin]
        d.line(x, y, x+70, y)
        d.ground(x+70, y)
    # Right NC pins 11,8
    for pin in [11, 8]:
        x, y = rcoords[pin]
        d.line(x, y, x+40, y)
        d.line(x+48, y-16, x+80, y+16, w=3)
        d.line(x+48, y+16, x+80, y-16, w=3)
        d.text(x+92, y+7, "NC", size=20, bold=True, c=MUTED)

    # U1 outputs through local series resistors to net labels.
    # The matching connector DATA pins use the same net labels; no long decorative wire is needed.
    r1_left, r1_right = 795, lcoords[3][0] - 30
    d.resistor_h(r1_left, lcoords[3][1], r1_right, "R1", "470Ω")
    d.line(r1_right, lcoords[3][1], lcoords[3][0], lcoords[3][1])
    d.net(r1_left, lcoords[3][1], "J1_DATA", c=GREEN, side="left")

    r2_left, r2_right = 795, lcoords[6][0] - 30
    d.resistor_h(r2_left, lcoords[6][1], r2_right, "R2", "470Ω")
    d.line(r2_right, lcoords[6][1], lcoords[6][0], lcoords[6][1])
    d.net(r2_left, lcoords[6][1], "J2_DATA", c=GREEN, side="left")

    # U1 VCC decoupling near physical pin 14 / pin 7
    d.text(2270, 735, "Decoupling at U1 pins 14/7", size=22, bold=True)
    d.net(2300, 790, "+5V_LOGIC", c=BLUE, side="right")
    d.line(2300, 790, 2300, 970)
    d.cap_v(2420, 790, 970, "C2", "0.1µF")
    d.cap_v(2580, 790, 970, "C3", "10µF")
    d.ground(2300, 970)
    d.ground(2420, 970)
    d.ground(2580, 970)

    # LED output connectors on right
    j1 = d.connector(2800, 1410, "J1 LED OUT", [("1", "V+"), ("2", "GND"), ("3", "DATA")], spacing=72)
    j2 = d.connector(2800, 1765, "J2 LED OUT", [("1", "V+"), ("2", "GND"), ("3", "DATA")], spacing=72)
    # V+ from +12 protected, GND from common, data from net labels
    for pt in [j1["V+"], j2["V+"]]:
        d.polyline([(2650, p12_y+23), (2650, pt[1]), pt])
        d.junction(2650, p12_y+23)
    for pt in [j1["GND"], j2["GND"]]:
        d.polyline([(2600, p12_y+111), (2600, pt[1]), pt])
        d.junction(2600, p12_y+111)
    # DATA pins use matching net labels from the U1 output resistors.
    d.net(j1["DATA"][0], j1["DATA"][1], "J1_DATA", c=GREEN, side="left")
    d.net(j2["DATA"][0], j2["DATA"][1], "J2_DATA", c=GREEN, side="left")

    # Notes/checks
    d.rect(80, 2065, 3140, 200, sw=3)
    d.text(110, 2105, "Must-meter checks before power", size=26, bold=True)
    d.text(110, 2145, "1) +12V_PROTECTED ↔ +5V_LOGIC = open/megaohms.  2) All GND points common ≈0Ω.  3) U1 pins 10 and 13 are +5V_LOGIC, not GND.", size=22)
    d.text(110, 2180, "4) U1 pin 14 gets USB-derived +5V only; do not backfeed ESP32 VIN from the 12V supply.  5) Full LED current stays off solderless breadboard.", size=22)
    d.text(110, 2215, "Top-view DIP orientation matters: notch at top, pin 1 upper-left, pin 14 upper-right.", size=22, bold=True, c=RED)

    d.text(W-90, H-38, "projects/lisbon-av-install • esp32-led-controller-v6-dip14-pin-location-schematic", size=18, c=MUTED, anchor="end")
    d.save()
    print(SVG_PATH)
    print(PNG_PATH)


if __name__ == "__main__":
    main()
