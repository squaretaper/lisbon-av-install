#!/usr/bin/env python3
"""Generate a readable, pin-explicit schematic for the ESP32 LED controller.

This is not a KiCad electrical-rule-checked schematic; it is a clean bench
reference generated from the audited v6 netlist.
"""
from __future__ import annotations

from pathlib import Path
import html

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "diagrams"
OUT.mkdir(parents=True, exist_ok=True)
SVG_PATH = OUT / "esp32-led-controller-v6-proper-schematic.svg"
PNG_PATH = OUT / "esp32-led-controller-v6-proper-schematic.png"

W, H = 2600, 1750
COLORS = {
    "bg": "#fafafa",
    "ink": "#151515",
    "muted": "#555",
    "grid": "#e5e7eb",
    "box": "#ffffff",
    "box2": "#f8fafc",
    "p12": "#c2410c",
    "p5": "#be185d",
    "gnd": "#111827",
    "data": "#d97706",
    "ok": "#047857",
    "warn": "#b45309",
    "blue": "#2563eb",
    "violet": "#5b21b6",
}

svg: list[str] = []

def esc(s: str) -> str:
    return html.escape(s, quote=True)


def add(s: str) -> None:
    svg.append(s)


def line(x1, y1, x2, y2, color="ink", w=4, dash: str | None = None) -> None:
    dash_attr = f' stroke-dasharray="{dash}"' if dash else ""
    add(f'<line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" stroke="{COLORS.get(color,color)}" stroke-width="{w}" stroke-linecap="round" fill="none"{dash_attr}/>' )


def poly(points, color="ink", w=4, fill="none", dash: str | None = None) -> None:
    pts = " ".join(f"{x},{y}" for x, y in points)
    dash_attr = f' stroke-dasharray="{dash}"' if dash else ""
    add(f'<polyline points="{pts}" stroke="{COLORS.get(color,color)}" stroke-width="{w}" stroke-linecap="round" stroke-linejoin="round" fill="{fill}"{dash_attr}/>' )


def rect(x, y, width, height, label: str | None = None, fill="box", stroke="ink", sw=3, rx=18, cls="") -> None:
    add(f'<rect x="{x}" y="{y}" width="{width}" height="{height}" rx="{rx}" fill="{COLORS.get(fill,fill)}" stroke="{COLORS.get(stroke,stroke)}" stroke-width="{sw}" class="{cls}"/>')
    if label:
        text(x + width / 2, y + height / 2, label, size=34, weight="700", anchor="middle", valign="middle")


def circle(x, y, r=8, fill="box", stroke="ink", sw=3) -> None:
    add(f'<circle cx="{x}" cy="{y}" r="{r}" fill="{COLORS.get(fill,fill)}" stroke="{COLORS.get(stroke,stroke)}" stroke-width="{sw}"/>')


def text(x, y, s, size=28, color="ink", weight="400", anchor="start", valign="baseline", family="Inter, Arial, Helvetica, sans-serif", rotate: int | None = None) -> None:
    dominant = "middle" if valign == "middle" else "auto"
    transform = f' transform="rotate({rotate} {x} {y})"' if rotate is not None else ""
    # SVG doesn't support line breaks in text reliably here; split manually.
    lines = str(s).split("\n")
    if len(lines) == 1:
        add(f'<text x="{x}" y="{y}" fill="{COLORS.get(color,color)}" font-family="{family}" font-size="{size}" font-weight="{weight}" text-anchor="{anchor}" dominant-baseline="{dominant}"{transform}>{esc(lines[0])}</text>')
    else:
        add(f'<text x="{x}" y="{y}" fill="{COLORS.get(color,color)}" font-family="{family}" font-size="{size}" font-weight="{weight}" text-anchor="{anchor}"{transform}>')
        for i, ln in enumerate(lines):
            dy = 0 if i == 0 else size * 1.25
            add(f'<tspan x="{x}" dy="{dy}">{esc(ln)}</tspan>')
        add('</text>')


def resistor(x1, y1, x2, y2, label, color="ink") -> None:
    # Draw horizontal or vertical resistor as rectangle in-line.
    if y1 == y2:
        xmid = (x1 + x2) / 2
        line(x1, y1, xmid - 55, y1, color, 4)
        rect(xmid - 55, y1 - 22, 110, 44, None, fill="#fff7ed", stroke=color, sw=3, rx=8)
        line(xmid + 55, y1, x2, y2, color, 4)
        text(xmid, y1 - 34, label, size=23, anchor="middle", color=color, weight="700")
    elif x1 == x2:
        ymid = (y1 + y2) / 2
        line(x1, y1, x1, ymid - 55, color, 4)
        rect(x1 - 24, ymid - 55, 48, 110, None, fill="#fff7ed", stroke=color, sw=3, rx=8)
        line(x1, ymid + 55, x2, y2, color, 4)
        text(x1 + 38, ymid, label, size=23, anchor="start", valign="middle", color=color, weight="700")


def cap(x, y_top, y_bottom, label, plus=True, color="ink") -> None:
    y = (y_top + y_bottom) / 2
    line(x, y_top, x, y - 28, color, 4)
    line(x - 38, y - 28, x + 38, y - 28, color, 5)
    line(x - 38, y + 28, x + 38, y + 28, color, 5)
    line(x, y + 28, x, y_bottom, color, 4)
    if plus:
        text(x + 52, y - 42, "+", size=34, color=color, weight="700")
    text(x + 58, y + 6, label, size=24, color=color, weight="700", valign="middle")


def led_series(x, y_top, y_bottom, label, rail_color="p12") -> None:
    resistor(x, y_top, x, (y_top+y_bottom)//2 - 52, label.split("+")[0].strip(), color=rail_color)
    y = (y_top+y_bottom)//2 + 18
    # LED symbol simplified: triangle/bar
    line(x, (y_top+y_bottom)//2 + 6, x, y - 34, rail_color, 4)
    add(f'<polygon points="{x-30},{y-34} {x+30},{y-34} {x},{y+18}" fill="none" stroke="{COLORS[rail_color]}" stroke-width="4"/>')
    line(x - 34, y + 22, x + 34, y + 22, rail_color, 4)
    line(x, y + 22, x, y_bottom, "gnd", 4)
    text(x + 48, y - 4, label, size=23, color=rail_color, weight="700", valign="middle")


def ground(x, y, label: str | None = None) -> None:
    line(x, y, x, y + 18, "gnd", 4)
    line(x - 28, y + 18, x + 28, y + 18, "gnd", 4)
    line(x - 20, y + 30, x + 20, y + 30, "gnd", 4)
    line(x - 10, y + 42, x + 10, y + 42, "gnd", 4)
    if label:
        text(x + 40, y + 34, label, size=23, color="gnd", valign="middle")


def label_box(x, y, s, color="ink", fill="#ffffff", anchor="start") -> None:
    lines = s.split("\n")
    max_len = max(len(l) for l in lines)
    w = max(140, max_len * 14 + 26)
    h = len(lines) * 28 + 18
    if anchor == "middle":
        x = x - w/2
    rect(x, y, w, h, None, fill=fill, stroke=color, sw=2, rx=10)
    for i, ln in enumerate(lines):
        text(x + 14, y + 32 + i*28, ln, size=22, color=color, weight="700" if i == 0 else "400")


add(f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}">')
add(f'<rect width="100%" height="100%" fill="{COLORS["bg"]}"/>')
add('<defs><marker id="arrow" markerWidth="10" markerHeight="10" refX="7" refY="3" orient="auto" markerUnits="strokeWidth"><path d="M0,0 L0,6 L7,3 z" fill="#d97706"/></marker></defs>')

# Title
text(80, 70, "ESP32 LED Controller v6 — Proper Schematic / Pin-Explicit Bench Reference", size=42, weight="800")
text(80, 115, "Key correction: SN74AHCT125 /OE pins are active-low. Pins 10 and 13 go to +5 V to DISABLE unused channels 3 and 4.", size=27, color="warn", weight="700")

# Section boundaries
rect(55, 155, 935, 1450, None, fill="#fff7ed", stroke="#fed7aa", sw=3, rx=24)
rect(1040, 155, 1505, 1450, None, fill="#eff6ff", stroke="#bfdbfe", sw=3, rx=24)
text(85, 205, "12 V LED POWER — high-current/off-breadboard", size=30, weight="800", color="p12")
text(1075, 205, "5 V LOGIC / DATA — breadboard/perfboard", size=30, weight="800", color="blue")

# Left power schematic coordinates
x_p = 220
rail12_x = 520
gnd_x = 820
line(rail12_x, 280, rail12_x, 1340, "p12", 7)
line(gnd_x, 280, gnd_x, 1400, "gnd", 7)
label_box(rail12_x, 238, "P12_PROTECTED\n12 V after fuse/RP1", color="p12", fill="#fff7ed", anchor="middle")
label_box(gnd_x, 238, "GND_COMMON\nPSU/LED/logic reference", color="gnd", fill="#f9fafb", anchor="middle")

rect(115, 285, 230, 80, "PSU1\nMean Well RS-150-12", fill="box", stroke="p12")
line(345, 325, 410, 325, "p12", 5)
resistor(410, 325, 540, 325, "F1 7.5A", "p12")
rect(585, 285, 210, 80, "RP1\nreverse protect", fill="#fff7ed", stroke="p12")
line(795, 325, rail12_x, 325, "p12", 5)
line(345, 352, gnd_x, 352, "gnd", 5)
circle(rail12_x, 325, 7, fill="p12", stroke="p12")
circle(gnd_x, 352, 7, fill="gnd", stroke="gnd")
text(115, 405, "RP1 = MOSFET ideal-diode or other part rated above fuse.\n1N5822 is OK only for tiny/current-limited prototype, not final 7.5 A path.", size=23, color="warn")

# C1 and power LED
cap(625, 505, 820, "C1 1000µF / 25V", plus=True, color="p12")
line(rail12_x, 505, 625, 505, "p12", 4)
line(625, 820, gnd_x, 820, "gnd", 4)
led_series(710, 570, 820, "R4 1k + LED2 green", rail_color="p12")
line(rail12_x, 570, 710, 570, "p12", 4)
line(710, 820, gnd_x, 820, "gnd", 4)

# Connectors J1/J2 power side
for y, ref in [(1010, "J1"), (1210, "J2")]:
    rect(245, y-70, 270, 145, f"{ref}\nLED output", fill="#ecfdf5", stroke="ok")
    text(275, y-24, "1 V+", size=24, color="p12", weight="700")
    text(275, y+18, "2 GND", size=24, color="gnd", weight="700")
    text(275, y+60, "3 DATA", size=24, color="data", weight="700")
    line(rail12_x, y-24, 515, y-24, "p12", 5)
    line(gnd_x, y+18, 515, y+18, "gnd", 5)
    circle(rail12_x, y-24, 7, fill="p12", stroke="p12")
    circle(gnd_x, y+18, 7, fill="gnd", stroke="gnd")
    # data enters from right side later
    line(515, y+60, 965, y+60, "data", 5)
    text(535, y+94, f"{ref}_DATA from AHCT125", size=22, color="data", weight="700")

ground(gnd_x, 1420, "common ground node")

# ESP32 box
rect(1110, 290, 380, 310, None, fill="#dbeafe", stroke="blue", sw=4, rx=20)
text(1300, 335, "ESP32 DevKit V1", size=31, weight="800", color="blue", anchor="middle")
text(1300, 376, "USB-C powered only", size=24, weight="700", color="blue", anchor="middle")
text(1300, 414, "VIN/5V = USB-derived tap\nDO NOT backfeed", size=22, color="warn", anchor="middle")
# ESP32 pins
pins_esp = [("VIN/5V", 1110, 470, "p5"), ("G25", 1110, 520, "data"), ("G26", 1110, 570, "data"), ("G27", 1490, 500, "data"), ("GND", 1490, 560, "gnd")]
for name, x, y, c in pins_esp:
    line(x-45 if x==1110 else x, y, x if x==1110 else x+45, y, c, 5)
    text(x+12 if x==1110 else x-12, y-8, name, size=23, color=c, weight="700", anchor="start" if x==1110 else "end")

# 5V and GND rails on right
p5_y = 700
gnd_y = 1410
line(1085, p5_y, 2390, p5_y, "p5", 7)
line(1085, gnd_y, 2390, gnd_y, "gnd", 7)
text(1090, p5_y-18, "P5_LOGIC_USB (+5 V from ESP32 USB/VIN only)", size=25, color="p5", weight="800")
text(1090, gnd_y-18, "GND_COMMON", size=25, color="gnd", weight="800")
line(1110-45, 470, 1060, 470, "p5", 5)
poly([(1060,470),(1060,p5_y),(1085,p5_y)], "p5", 5)
line(1535, 560, 1580, 560, "gnd", 5)
poly([(1580,560),(1580,gnd_y)], "gnd", 5)

# Status LED
resistor(1535, 500, 1710, 500, "R3 220Ω", "data")
add(f'<polygon points="1730,466 1730,534 1786,500" fill="none" stroke="{COLORS["data"]}" stroke-width="4"/>')
line(1790, 464, 1790, 536, "data", 4)
line(1790, 500, 1790, gnd_y, "gnd", 4)
text(1725, 445, "LED1 red status", size=22, color="data", weight="700")

# U1 DIP
u_x, u_y, u_w, u_h = 1640, 815, 430, 500
rect(u_x, u_y, u_w, u_h, None, fill="#ede9fe", stroke="violet", sw=4, rx=18)
text(u_x+u_w/2, u_y+42, "U1 SN74AHCT125N", size=29, weight="800", color="violet", anchor="middle")
text(u_x+u_w/2, u_y+78, "DIP-14 quad buffer — /OE is ACTIVE-LOW", size=22, weight="700", color="warn", anchor="middle")
# notch
add(f'<path d="M {u_x+u_w/2-38} {u_y} a38 26 0 0 0 76 0" fill="{COLORS["bg"]}" stroke="{COLORS["violet"]}" stroke-width="3"/>')

left_pins = [
    (1, "/OE1", "GND enables CH1", "gnd"),
    (2, "1A", "GPIO25", "data"),
    (3, "1Y", "R1 → J1 DATA", "data"),
    (4, "/OE2", "GND enables CH2", "gnd"),
    (5, "2A", "GPIO26", "data"),
    (6, "2Y", "R2 → J2 DATA", "data"),
    (7, "GND", "common ground", "gnd"),
]
right_pins = [
    (14, "VCC", "+5 V logic", "p5"),
    (13, "/OE4", "+5 V disables CH4", "p5"),
    (12, "4A", "GND defined input", "gnd"),
    (11, "4Y", "NC", "muted"),
    (10, "/OE3", "+5 V disables CH3", "p5"),
    (9, "3A", "GND defined input", "gnd"),
    (8, "3Y", "NC", "muted"),
]
left_y = [u_y+120+i*56 for i in range(7)]
right_y = left_y
for (pin, name, desc, c), y in zip(left_pins, left_y):
    line(u_x-75, y, u_x, y, c, 5)
    text(u_x+18, y+7, f"{pin} {name}", size=22, color=c, weight="800")
    text(u_x-86, y+7, desc, size=21, color=c, anchor="end", weight="700" if pin in (1,4,7) else "400")
for (pin, name, desc, c), y in zip(right_pins, right_y):
    line(u_x+u_w, y, u_x+u_w+75, y, c, 5 if c != "muted" else 3)
    text(u_x+u_w-18, y+7, f"{pin} {name}", size=22, color=c, weight="800", anchor="end")
    text(u_x+u_w+86, y+7, desc, size=21, color=c, anchor="start", weight="700" if pin in (10,13,14) else "400")

# U1 connections
# pin14 to p5, pins 10/13 to p5
for idx, (pin, _, _, c) in enumerate(right_pins):
    y = right_y[idx]
    if pin in (14,13,10):
        poly([(u_x+u_w+75, y), (2220, y), (2220, p5_y)], "p5", 4)
    if pin in (12,9):
        poly([(u_x+u_w+75, y), (2290, y), (2290, gnd_y)], "gnd", 4)
# pin7, oe1, oe2 to ground
for idx, (pin, _, _, c) in enumerate(left_pins):
    y = left_y[idx]
    if pin in (1,4,7):
        poly([(u_x-75, y), (1540, y), (1540, gnd_y)], "gnd", 4)
# ESP32 data to U1 inputs
poly([(1110-45,520),(1055,520),(1055,left_y[1]),(u_x-75,left_y[1])], "data", 5)
text(1160, 506, "GPIO25 → 1A", size=22, color="data", weight="700")
poly([(1110-45,570),(1030,570),(1030,left_y[4]),(u_x-75,left_y[4])], "data", 5)
text(1160, 556, "GPIO26 → 2A", size=22, color="data", weight="700")
# Outputs to resistors and J1/J2 data lines
resistor(u_x-75, left_y[2], 1390, left_y[2], "R1 470Ω", "data")
poly([(1390,left_y[2]),(1005,left_y[2]),(1005,1010+60),(965,1010+60)], "data", 5)
text(1210, left_y[2]-35, "1Y → J1 data", size=22, color="data", weight="700")
resistor(u_x-75, left_y[5], 1390, left_y[5], "R2 470Ω", "data")
poly([(1390,left_y[5]),(1030,left_y[5]),(1030,1210+60),(965,1210+60)], "data", 5)
text(1210, left_y[5]-35, "2Y → J2 data", size=22, color="data", weight="700")
# NC stubs for right pins 11/8
for idx, (pin, _, _, c) in enumerate(right_pins):
    if pin in (11,8):
        y=right_y[idx]
        line(u_x+u_w+75, y, u_x+u_w+125, y, "muted", 3)
        text(u_x+u_w+138, y+7, "leave open", size=19, color="muted")

# Decoupling caps near U1
cap(2180, p5_y, gnd_y, "C2 0.1µF at pins 14/7", plus=True, color="p5")
cap(2355, p5_y, gnd_y, "C3 10µF nearby", plus=True, color="p5")

# Common ground connection between power and logic, low-current reference
poly([(gnd_x, 1400), (980, 1400), (980, gnd_y), (1085, gnd_y)], "gnd", 5, dash="12 10")
text(900, 1370, "one common-ground reference\nload current returns off-board", size=22, color="gnd", weight="700", anchor="middle")

# Notes box
rect(90, 1500, 2390, 100, None, fill="#fff", stroke="#d1d5db", sw=2, rx=16)
text(115, 1534, "SN74AHCT125 OE truth: /OE = LOW enables A→Y; /OE = HIGH disables output to high-Z. Therefore used pins 1 & 4 go to GND; unused pins 10 & 13 go to +5 V.", size=24, color="ink", weight="800")
text(115, 1574, "If pins 10/13 were tied to GND, channels 3/4 would be enabled; with inputs tied GND and outputs NC it usually would not damage anything, but it is not the clean disabled-state schematic.", size=22, color="muted")

# Net legend
legend_x, legend_y = 2140, 250
rect(legend_x, legend_y, 350, 210, None, fill="#ffffff", stroke="#d1d5db", sw=2, rx=16)
text(legend_x+20, legend_y+38, "Legend", size=25, weight="800")
for i,(name,c) in enumerate([("12 V protected", "p12"), ("5 V logic", "p5"), ("GND common", "gnd"), ("Data/signal", "data")]):
    y=legend_y+74+i*32
    line(legend_x+24,y,legend_x+90,y,c,6)
    text(legend_x+105,y+8,name,size=21,color=c,weight="700")

add('</svg>')
SVG_PATH.write_text("\n".join(svg), encoding="utf-8")

# Also generate a readable PNG directly with Pillow if available.
try:
    from PIL import Image, ImageDraw, ImageFont

    img = Image.new("RGB", (W, H), COLORS["bg"])
    draw = ImageDraw.Draw(img)
    try:
        font_big = ImageFont.truetype("/System/Library/Fonts/Supplemental/Arial Bold.ttf", 48)
        font_h = ImageFont.truetype("/System/Library/Fonts/Supplemental/Arial Bold.ttf", 34)
        font = ImageFont.truetype("/System/Library/Fonts/Supplemental/Arial.ttf", 28)
        font_small = ImageFont.truetype("/System/Library/Fonts/Supplemental/Arial.ttf", 22)
        font_small_b = ImageFont.truetype("/System/Library/Fonts/Supplemental/Arial Bold.ttf", 22)
    except Exception:
        font_big = font_h = font = font_small = font_small_b = ImageFont.load_default()

    def dtext(x, y, s, fill=COLORS["ink"], f=font, anchor=None):
        draw.text((x,y), s, fill=fill, font=f, anchor=anchor)

    # Instead of duplicating every SVG detail, make a compact PNG readme card with the critical pinout.
    draw.rounded_rectangle((40,40,W-40,H-40), radius=28, fill="#ffffff", outline="#d1d5db", width=4)
    dtext(90,90,"ESP32 LED Controller v6 — Proper Schematic Quick View", f=font_big)
    dtext(90,155,"Full vector schematic: esp32-led-controller-v6-proper-schematic.svg", fill=COLORS["muted"], f=font)
    dtext(90,220,"Critical AHCT125N correction", fill=COLORS["warn"], f=font_big)
    bullets = [
        "SN74AHCT125 /OE pins are ACTIVE-LOW.",
        "Pins 1 and 4 -> GND: enable the two used buffers.",
        "Pins 10 and 13 -> +5 V logic: disable unused buffers 3 and 4.",
        "Pins 9 and 12 -> GND: define unused inputs.",
        "Pins 8 and 11 -> NC: unused disabled outputs float / high-Z.",
        "Pins 3 and 6 are separate outputs: do NOT tie J1/J2 data together.",
    ]
    yy = 300
    for b in bullets:
        dtext(130, yy, "• " + b, f=font_h if "10" in b or "1 and 4" in b else font, fill=COLORS["ink"])
        yy += 62
    # Draw a simple pin table
    x0,y0=90,760
    colw=[110,180,540,540]
    headers=["Pin","Name","Connection","Why"]
    draw.rectangle((x0,y0,x0+sum(colw),y0+54), fill="#ede9fe", outline="#5b21b6", width=3)
    x=x0
    for h,cw in zip(headers,colw):
        dtext(x+12,y0+14,h,f=font_small_b,fill=COLORS["violet"])
        x+=cw
    rows=[
        ("1","/OE1","GND","enable buffer 1 for J1"),
        ("4","/OE2","GND","enable buffer 2 for J2"),
        ("10","/OE3","+5 V logic","disable unused buffer 3"),
        ("13","/OE4","+5 V logic","disable unused buffer 4"),
        ("9","3A","GND","defined unused input"),
        ("12","4A","GND","defined unused input"),
        ("8","3Y","NC","disabled output, leave open"),
        ("11","4Y","NC","disabled output, leave open"),
    ]
    yy=y0+54
    for r,row in enumerate(rows):
        fill="#f8fafc" if r%2==0 else "#ffffff"
        draw.rectangle((x0,yy,x0+sum(colw),yy+58), fill=fill, outline="#d1d5db", width=1)
        x=x0
        for val,cw in zip(row,colw):
            color=COLORS["p5"] if "+5" in val else COLORS["gnd"] if val == "GND" else COLORS["ink"]
            dtext(x+12,yy+16,val,f=font_small_b if val in ("GND","+5 V logic") else font_small,fill=color)
            x+=cw
        yy+=58
    dtext(90, yy+50, "For the complete schematic layout, open the SVG. This PNG is intentionally a high-contrast pinout card.", fill=COLORS["muted"], f=font)
    img.save(PNG_PATH)
except Exception as e:
    PNG_PATH.write_text(f"PNG generation skipped: {e}\n", encoding="utf-8")

print(SVG_PATH)
print(PNG_PATH)
