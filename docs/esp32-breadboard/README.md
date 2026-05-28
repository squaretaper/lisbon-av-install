# ESP32 Breadboard Audit Pack

Start here for today’s build:

1. `datasheet-evidence.md` — source-backed component constraints.
2. `revised-audited-schematic.md` — corrected schematic/netlist narrative.
3. `breadboard-wiring-checklist.md` — bench wiring and meter checks.
4. `netlist.json` — machine-checkable circuit netlist.
5. `bom.csv` — parts/BOM audit.

Diagrams / KiCad source:

- `../../kicad/esp32-led-controller-v6-standard/esp32-led-controller-v6-standard.kicad_sch` — **primary reviewed standard KiCad schematic**. U1 is explicitly `SN74AHCT125N`, drawn as conventional units `U1A`/`U1B`/`U1C`/`U1D` plus `U1P` power.
- `../../diagrams/kicad-standard/esp32-led-controller-v6-standard.svg` — KiCad SVG export of the standard schematic; visually checked after revision for no cropped components or text/symbol overlaps.
- `../../diagrams/kicad-standard/esp32-led-controller-v6-standard-schematic.pdf` — printable standard schematic PDF.
- `../../diagrams/kicad-standard/esp32-led-controller-v6-standard-schematic.png` — uncropped high-resolution PNG preview for quick bench viewing.
- `../../diagrams/kicad-standard/esp32-led-controller-v6-standard.net` — KiCad-exported netlist for the standard schematic; checked against the verified critical nets.
- `../../kicad/esp32-led-controller-v6/esp32-led-controller-v6.kicad_sch` — companion bench pin-location sheet. U1 is drawn as DIP-14 top-view: notch up, pin 1 upper-left, pins 1–7 left, pins 14–8 right.
- `../../diagrams/kicad/esp32-led-controller-v6.svg` — KiCad SVG export of the bench pin-location sheet.
- `../../diagrams/kicad/esp32-led-controller-v6-kicad-bench-schematic.pdf` — printable bench pin-location PDF export.
- `../../diagrams/kicad/esp32-led-controller-v6-kicad-bench-schematic.png` — PNG preview of the bench pin-location sheet.
- `../../diagrams/kicad/esp32-led-controller-v6-kicad.net` — KiCad-exported netlist for the bench pin-location sheet.
- `../../diagrams/esp32-led-controller-v6-dip14-pin-location-schematic.svg` — older hand-generated bench-wiring schematic with U1 drawn as the actual DIP-14 top view: notch up, pin 1 upper-left, pins 1–7 left, pins 14–8 right.
- `../../diagrams/esp32-led-controller-v6-dip14-pin-location-schematic.png` — PNG export of the older DIP-14 pin-location schematic.
- `../../diagrams/esp32-led-controller-v6-electrical-schematic.svg` — older conventional symbol-based electrical schematic.
- `../../diagrams/esp32-led-controller-v6-electrical-schematic.png` — PNG export of the older conventional electrical schematic for quick bench viewing.
- `../../diagrams/esp32-led-controller-v6-u1-ahct125-schematic.svg` — clearest U1/SN74AHCT125N logic-symbol schematic; use this for pins 1/4/10/13 and J1/J2 data wiring.
- `../../diagrams/esp32-led-controller-v6-u1-ahct125-schematic.png` — quick PNG pin-answer card for the AHCT125N.
- `../../diagrams/esp32-led-controller-v6-proper-schematic.svg` — larger full-system pin-explicit schematic.
- `../../diagrams/esp32-led-controller-v6-proper-schematic.png` — high-contrast quick pinout card for U1 `/OE` pins.
- `../../diagrams/esp32-led-controller-v6-breadboard.svg` — generated breadboard/block schematic.
- `../../diagrams/esp32-led-controller-v6-breadboard.png` — PNG preview for quick bench reference.
- `../../diagrams/esp32-led-controller-v6-breadboard.excalidraw` — editable diagram source.

Validation:

```bash
python3 scripts/validate-esp32-netlist.py
python3 scripts/generate-kicad-standard-schematic.py
kicad-cli sch export netlist --output diagrams/kicad-standard/esp32-led-controller-v6-standard.net kicad/esp32-led-controller-v6-standard/esp32-led-controller-v6-standard.kicad_sch
```

Latest regenerated standard KiCad sheet passed:

- `PASS: ESP32 v6 breadboard netlist isolation and required connections verified.`
- `PASS: reviewed standard KiCad netlist is 1:1 with verified critical nets.`
- Browser visual inspection of the SVG export found no definite text/symbol overlaps or cropping after the LED2/title-block and U1-label revisions.
