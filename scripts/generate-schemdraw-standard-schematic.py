#!/usr/bin/env python3
"""Generate a standard-looking schematic using the schemdraw library.

Unlike the earlier hand-drawn SVGs, this uses a schematic drawing package for
normal component symbols. U1 is still drawn as a physical DIP-14 top-view symbol
because this sheet is meant for bench wiring.
"""
from __future__ import annotations

from pathlib import Path
import schemdraw
from schemdraw import elements as elm

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "diagrams"
OUT.mkdir(exist_ok=True)
SVG = OUT / "esp32-led-controller-v6-schemdraw-standard-schematic.svg"
PNG = OUT / "esp32-led-controller-v6-schemdraw-standard-schematic.png"

schemdraw.use("svg")


def add_net(d: schemdraw.Drawing, at, label: str, color: str = "black"):
    d += elm.Dot(open=True).at(at).color(color)
    d += elm.Label().at((at[0] + 0.18, at[1] + 0.08)).label(label, loc="right", fontsize=10).color(color)


def add_nc(d: schemdraw.Drawing, at, side="right"):
    x, y = at
    dx = 0.35 if side == "right" else -0.35
    d += elm.Line().at((x, y)).to((x + dx, y))
    x2 = x + dx
    d += elm.Line().at((x2 - 0.08, y - 0.08)).to((x2 + 0.08, y + 0.08))
    d += elm.Line().at((x2 - 0.08, y + 0.08)).to((x2 + 0.08, y - 0.08))
    d += elm.Label().at((x2 + (0.12 if side == "right" else -0.12), y + 0.04)).label("NC", fontsize=9, loc="right" if side == "right" else "left")


def gnd_at(d: schemdraw.Drawing, at, label: str | None = None):
    d += elm.Line().at(at).down().length(0.25)
    d += elm.Ground()
    if label:
        d += elm.Label().at((at[0] + 0.25, at[1] - 0.45)).label(label, fontsize=8, loc="right")


def vdd_at(d: schemdraw.Drawing, at, label="+5V_LOGIC", color="black"):
    d += elm.Line().at(at).up().length(0.25).color(color)
    d += elm.Vdd().label(label, fontsize=9).color(color)


def draw():
    with schemdraw.Drawing(file=str(SVG), show=False) as d:
        d.config(unit=2.0, fontsize=10, lw=1.4)

        # Title
        d += elm.Label().at((0, 10.8)).label("ESP32 LED Controller v6 — standard schemdraw schematic", fontsize=16, loc="right")
        d += elm.Label().at((0, 10.25)).label("U1 is shown as physical DIP-14 top view: notch up, pin 1 upper-left, pin 14 upper-right", fontsize=11, loc="right")
        d += elm.Label().at((0, 9.82)).label("/OE pins are active-low: pins 1/4 to GND enable used channels; pins 10/13 to +5V_LOGIC disable unused channels", fontsize=10, loc="right").color("red")

        # 12V power input chain, top-left
        d += elm.Label().at((0, 9.0)).label("12 V LED POWER", fontsize=12, loc="right")
        j3 = d.add(elm.Ic(size=(1.35, 1.0), pins=[
            elm.IcPin(name="+12V", pin="1", side="R", slot="1/2", anchorname="p1"),
            elm.IcPin(name="GND", pin="2", side="R", slot="2/2", anchorname="p2"),
        ]).at((0.1, 7.7)).label("J3\n12V IN", fontsize=9))
        d += elm.Line().at(j3.p1).right().length(0.55)
        d += elm.Fuse().right().label("F1\n7.5A", fontsize=8)
        d += elm.Diode().right().label("D1/RP1\n1N5822 proto only", fontsize=8)
        p12node = d.here
        add_net(d, p12node, "+12V_PROTECTED", "red")
        d += elm.Line().at(j3.p2).right().length(2.9)
        gndnode = d.here
        add_net(d, gndnode, "GND_COMMON")

        # C1 and power LED to ground
        d += elm.Line().at(p12node).down().length(1.3)
        d += elm.Capacitor(polar=True).down().label("C1\n1000µF/25V", fontsize=8)
        gnd_at(d, d.here)
        d += elm.Line().at((p12node[0] + 1.25, p12node[1])).down().length(0.75)
        d += elm.Resistor().down().label("R4\n1k", fontsize=8)
        d += elm.LED().down().label("LED2 green", fontsize=8)
        gnd_at(d, d.here)

        # ESP32 devkit at left-middle
        esp = d.add(elm.Ic(size=(2.5, 4.4), pins=[
            elm.IcPin(name="VIN/5V", pin="", side="R", slot="1/5", anchorname="vin"),
            elm.IcPin(name="GND", pin="", side="R", slot="2/5", anchorname="gnd"),
            elm.IcPin(name="GPIO25", pin="", side="R", slot="3/5", anchorname="g25"),
            elm.IcPin(name="GPIO26", pin="", side="R", slot="4/5", anchorname="g26"),
            elm.IcPin(name="GPIO27", pin="", side="R", slot="5/5", anchorname="g27"),
        ]).at((0.15, 1.35)).label("ESP32\nDevKit V1\nUSB only", fontsize=9))
        vdd_at(d, esp.vin, "+5V_LOGIC\nfrom USB only", color="blue")
        gnd_at(d, esp.gnd, "GND_COMMON")

        # U1 DIP14 top-view symbol
        left_pins = [
            elm.IcPin(name="/OE1", pin="1", side="L", slot="1/7", anchorname="p1"),
            elm.IcPin(name="1A", pin="2", side="L", slot="2/7", anchorname="p2"),
            elm.IcPin(name="1Y", pin="3", side="L", slot="3/7", anchorname="p3"),
            elm.IcPin(name="/OE2", pin="4", side="L", slot="4/7", anchorname="p4"),
            elm.IcPin(name="2A", pin="5", side="L", slot="5/7", anchorname="p5"),
            elm.IcPin(name="2Y", pin="6", side="L", slot="6/7", anchorname="p6"),
            elm.IcPin(name="GND", pin="7", side="L", slot="7/7", anchorname="p7"),
        ]
        right_pins = [
            elm.IcPin(name="VCC", pin="14", side="R", slot="1/7", anchorname="p14"),
            elm.IcPin(name="/OE4", pin="13", side="R", slot="2/7", anchorname="p13"),
            elm.IcPin(name="4A", pin="12", side="R", slot="3/7", anchorname="p12"),
            elm.IcPin(name="4Y", pin="11", side="R", slot="4/7", anchorname="p11"),
            elm.IcPin(name="/OE3", pin="10", side="R", slot="5/7", anchorname="p10"),
            elm.IcPin(name="3A", pin="9", side="R", slot="6/7", anchorname="p9"),
            elm.IcPin(name="3Y", pin="8", side="R", slot="7/7", anchorname="p8"),
        ]
        u1 = d.add(elm.Ic(size=(3.5, 6.4), pins=left_pins + right_pins).at((6.4, 2.1)).label("U1\nSN74AHCT125N\nDIP-14 TOP VIEW\nnotch up", fontsize=9))

        # Used OE pins and ground/power pins
        for pin in [u1.p1, u1.p4, u1.p7]:
            d += elm.Line().at(pin).left().length(0.45)
            gnd_at(d, d.here)
        vdd_at(d, u1.p14, "+5V_LOGIC", color="blue")

        # Unused channels disabled and defined
        for pin in [u1.p13, u1.p10]:
            vdd_at(d, pin, "+5V_LOGIC", color="blue")
        for pin in [u1.p12, u1.p9]:
            d += elm.Line().at(pin).right().length(0.35)
            gnd_at(d, d.here)
        add_nc(d, u1.p11, side="right")
        add_nc(d, u1.p8, side="right")

        # ESP32 data into U1 physical input pins
        d += elm.Line().at(esp.g25).right().tox(4.15).toy(u1.p2[1]).tox(u1.p2[0])
        d += elm.Label().at((4.2, u1.p2[1] + 0.22)).label("GPIO25 → U1 pin 2", fontsize=8, loc="right")
        d += elm.Line().at(esp.g26).right().tox(4.45).toy(u1.p5[1]).tox(u1.p5[0])
        d += elm.Label().at((4.2, u1.p5[1] - 0.26)).label("GPIO26 → U1 pin 5", fontsize=8, loc="right")

        # U1 outputs through series resistors to named nets.
        d += elm.Line().at(u1.p3).left().length(0.5)
        d += elm.Resistor().left().label("R1\n470Ω", fontsize=8)
        add_net(d, d.here, "J1_DATA", "green")
        d += elm.Line().at(u1.p6).left().length(0.5)
        d += elm.Resistor().left().label("R2\n470Ω", fontsize=8)
        add_net(d, d.here, "J2_DATA", "green")

        # Decoupling near U1
        d += elm.Label().at((11.1, 5.7)).label("U1 decoupling\nclose to pins 14/7", fontsize=9, loc="right")
        d += elm.Line().at((11.2, 5.2)).right().length(0.6)
        vdd_at(d, (11.2, 5.2), "+5V_LOGIC", color="blue")
        d += elm.Capacitor().at((12.0, 5.2)).down().label("C2\n0.1µF", fontsize=8)
        gnd_at(d, d.here)
        d += elm.Capacitor().at((13.0, 5.2)).down().label("C3\n10µF", fontsize=8)
        gnd_at(d, d.here)

        # Status LED from GPIO27
        d += elm.Line().at(esp.g27).right().length(0.65)
        d += elm.Resistor().down().label("R3\n220Ω", fontsize=8)
        d += elm.LED().down().label("LED1 red\nstatus", fontsize=8)
        gnd_at(d, d.here)

        # LED output connectors, right side, with net labels instead of long crossing wires
        j1 = d.add(elm.Ic(size=(1.6, 1.6), pins=[
            elm.IcPin(name="V+", pin="1", side="L", slot="1/3", anchorname="v"),
            elm.IcPin(name="GND", pin="2", side="L", slot="2/3", anchorname="g"),
            elm.IcPin(name="DATA", pin="3", side="L", slot="3/3", anchorname="d"),
        ]).at((13.0, 1.4)).label("J1 LED OUT", fontsize=8))
        j2 = d.add(elm.Ic(size=(1.6, 1.6), pins=[
            elm.IcPin(name="V+", pin="1", side="L", slot="1/3", anchorname="v"),
            elm.IcPin(name="GND", pin="2", side="L", slot="2/3", anchorname="g"),
            elm.IcPin(name="DATA", pin="3", side="L", slot="3/3", anchorname="d"),
        ]).at((13.0, -1.0)).label("J2 LED OUT", fontsize=8))
        for conn, data_label in [(j1, "J1_DATA"), (j2, "J2_DATA")]:
            add_net(d, conn.v, "+12V_PROTECTED", "red")
            d += elm.Line().at(conn.g).left().length(0.45)
            gnd_at(d, d.here)
            add_net(d, conn.d, data_label, "green")

        # Bottom notes / meter checks
        d += elm.Label().at((0, -1.7)).label("Meter before power: +12V_PROTECTED ↔ +5V_LOGIC = open/megaohms; all GND points ≈0Ω; U1 pin 14 gets USB-derived +5V only.", fontsize=10, loc="right")
        d += elm.Label().at((0, -2.15)).label("Full LED current stays off solderless breadboard. 1N5822 is prototype/current-limited only, not final multi-amp protection.", fontsize=10, loc="right").color("red")

    print(SVG)
    print('PNG preview must be rendered separately, e.g. with Playwright/Chrome screenshot:', PNG)


if __name__ == "__main__":
    draw()
