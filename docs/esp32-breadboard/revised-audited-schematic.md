# Revised + Double-Audited Schematic — ESP32 LED Controller v6 Breadboard

## Verdict

The architecture is sound **after revisions**:

- 12 V LED power rail and USB-derived 5 V logic rail remain isolated.
- ESP32 GPIO25/GPIO26 drive WS2811 data through a 5 V AHCT125 buffer.
- The AHCT125 pin map is corrected and unused channels are made unambiguous.
- The original 1N5822-in-full-current-path design is rejected for the 7.5 A / RS-150-12 build.
- Breadboarding is approved for logic/data validation, **not for carrying multi-amp LED current through solderless breadboard rails**.

## Critical changes from the original drawing

1. **D1 1N5822 is no longer approved as full-current reverse-polarity protection.**
   - Vishay rates 1N5822 IF(AV) at 3.0 A under specified lead-temperature conditions.
   - The project fuse is 7.5 A and the RS-150-12 can supply 12.5 A.
   - Revised schematic uses `RP1`: a high-current reverse-polarity block, preferably P-channel MOSFET / ideal-diode style, or a diode/rectifier rated above the fuse with real thermal design.

2. **AHCT125 outputs 1Y and 2Y are separate.**
   - `U1 pin 3 / 1Y → R1 470 Ω → J1 DATA`
   - `U1 pin 6 / 2Y → R2 470 Ω → J2 DATA`
   - They must never share a common output node.

3. **Unused AHCT125 channels are disabled cleanly.**
   - AHCT125 output enables are active-low (`/OE`). Datasheets state OE low passes A to Y; OE high makes Y high-impedance.
   - Used OEs: `pin 1 /OE1` and `pin 4 /OE2` → GND.
   - Unused OEs: `pin 10 /OE3` and `pin 13 /OE4` → 5 V logic/VCC, so pins 8/11 are high-Z.
   - Unused inputs: `pin 9 /3A` and `pin 12 /4A` → GND.
   - Unused outputs: `pin 8 /3Y` and `pin 11 /4Y` → NC.
   - Some hobby diagrams, including Adafruit's Raspberry Pi DotStar level-shifter example, appear to tie unused OE pins low. That leaves unused buffers enabled. With grounded inputs and NC outputs it can still work, but the datasheet-clean version is unused OE high, unused inputs defined, unused outputs NC.
   - If pins 10/13 were tied to GND, unused channels 3/4 would be enabled; with inputs tied GND and outputs NC it usually would not damage anything, but it is not the clean disabled-state schematic.

4. **C2/C3 are explicitly across U1 VCC/GND.**
   - C2: 0.1 µF directly at `pin 14 ↔ pin 7`.
   - C3: 10 µF nearby across 5 V logic and GND.

## Revised topology

```text
12 V high-current side, off breadboard:
Mean Well RS-150-12 +
  → F1 source-side 7.5 A blade fuse
  → RP1 high-current reverse-polarity protection block
  → P12_PROTECTED rail
  → C1+ / LED2+R4 / J1 V+ / J2 V+

Mean Well RS-150-12 −
  → POWER_GND_BUS
  → C1− / J1 GND / J2 GND
  → separate low-current jumper to breadboard GND

5 V logic side, on breadboard/perfboard:
ESP32 USB-C only
  → ESP32 VIN/5V_FROM_USB_DO_NOT_BACKFEED
  → U1 pin 14 VCC / C2+ / C3+

Ground:
POWER_GND_BUS ↔ ESP32 GND ↔ U1 pin 7 ↔ C2−/C3− ↔ LED cathodes
```

## AHCT125 pin map

For the standard electrical schematic, use the reviewed logical KiCad sheet first. It draws the AHCT125 as an explicit multi-unit `SN74AHCT125N` part rather than hiding it in a generic-looking block:

- `U1A`: active J1 data buffer.
- `U1B`: active J2 data buffer.
- `U1C`/`U1D`: unused buffers, disabled with `/OE3`/`/OE4` tied high.
- `U1P`: package power pins, pin 14 VCC and pin 7 GND.

The latest export was visually rechecked for no cropped components and no definite text/symbol overlaps, and its KiCad netlist was checked 1:1 against the verified critical nets:

- `../../kicad/esp32-led-controller-v6-standard/esp32-led-controller-v6-standard.kicad_sch`
- `../../diagrams/kicad-standard/esp32-led-controller-v6-standard.svg`
- `../../diagrams/kicad-standard/esp32-led-controller-v6-standard-schematic.pdf`
- `../../diagrams/kicad-standard/esp32-led-controller-v6-standard-schematic.png`
- `../../diagrams/kicad-standard/esp32-led-controller-v6-standard.net`

For bench IC placement, use the separate KiCad pin-location sheet. It shows U1 as a DIP-14 top-view symbol with notch up and pin 1 upper-left:

- `../../kicad/esp32-led-controller-v6/esp32-led-controller-v6.kicad_sch`
- `../../diagrams/kicad/esp32-led-controller-v6.svg`
- `../../diagrams/kicad/esp32-led-controller-v6-kicad-bench-schematic.pdf`
- `../../diagrams/kicad/esp32-led-controller-v6-kicad-bench-schematic.png`
- `../../diagrams/kicad/esp32-led-controller-v6-kicad.net`

Older generated reference diagrams remain available, but the two KiCad sheets above are now the primary artifacts:

- `../../diagrams/esp32-led-controller-v6-dip14-pin-location-schematic.svg`
- `../../diagrams/esp32-led-controller-v6-dip14-pin-location-schematic.png`
- `../../diagrams/esp32-led-controller-v6-electrical-schematic.svg`
- `../../diagrams/esp32-led-controller-v6-electrical-schematic.png`
- `../../diagrams/esp32-led-controller-v6-u1-ahct125-schematic.svg`
- `../../diagrams/esp32-led-controller-v6-u1-ahct125-schematic.png`

| Pin | Name | Revised connection |
|---:|---|---|
| 1 | /OE1 | GND, enables J1 buffer |
| 2 | 1A | ESP32 GPIO25 |
| 3 | 1Y | R1 470 Ω → J1 DATA |
| 4 | /OE2 | GND, enables J2 buffer |
| 5 | 2A | ESP32 GPIO26 |
| 6 | 2Y | R2 470 Ω → J2 DATA |
| 7 | GND | common ground |
| 8 | 3Y | NC |
| 9 | 3A | GND |
| 10 | /OE3 | 5 V logic/VCC, disables unused buffer 3 |
| 11 | 4Y | NC |
| 12 | 4A | GND |
| 13 | /OE4 | 5 V logic/VCC, disables unused buffer 4 |
| 14 | VCC | ESP32 VIN / USB-derived 5 V only |

## Signal/data map

| Channel | ESP32 | AHCT input | AHCT output | Series R | Connector |
|---|---|---|---|---|---|
| J1 DATA | GPIO25 | U1 pin 2 / 1A | U1 pin 3 / 1Y | R1 470 Ω | J1 pin 3 DATA |
| J2 DATA | GPIO26 | U1 pin 5 / 2A | U1 pin 6 / 2Y | R2 470 Ω | J2 pin 3 DATA |
| Status LED | GPIO27 | — | — | R3 220 Ω | LED1 red → GND |

## Current / heat calculations

- LED1 status current: `5.9 mA`; R3 dissipation `7.7 mW`.
- LED2 power-good current: `9.9 mA`; R4 dissipation `98.0 mW`; use 1/4 W minimum.
- A 1N5822 at 3 A and VF=0.525 V dissipates `1.58 W`.
- At 7.5 A and ~0.7 V, a Schottky would dissipate `5.25 W`, not acceptable on a casual breadboard/perfboard path.

## Breadboard rule

Use the breadboard for:

- ESP32 signal wiring.
- AHCT125 level shifting.
- C2/C3 decoupling.
- Status LED.
- Data resistors.
- Common-ground reference jumper.

Do **not** use solderless breadboard rails for:

- Full LED strip 12 V current.
- Full LED strip ground return current.
- Fuse holder current.
- Reverse-protection diode/MOSFET heat/current path.



## Breadboarding the LED path — verified answer

A tiny LED path can be part of the breadboard prototype if it is separately current-limited. The installation-current LED path is not breadboard-safe.

- Known-quality BB830-style solderless breadboards are documented at 36 V / 2 A.
- Full-white WS2811-style pixels are commonly budgeted at about 60 mA per pixel/segment.
- 10 full-white pixels ≈ 0.6 A; 50 full-white pixels ≈ 3 A; the 7.5 A fuse threshold is well above breadboard rating.
- For first prototype, use ≤8 full-white-equivalent pixels or set bench supply current limit ≤0.5 A. If the strip needs more, move LED V+ and LED GND off-board.

## Approved test order

1. USB only, no 12 V: verify ESP32 boots and U1 pin 14 reads about 5 V.
2. USB only: firmware toggles GPIO27 status LED.
3. USB only: scope/logic probe U1 pins 3 and 6; verify separate data outputs.
4. 12 V only, no ESP32 USB, no strips: verify protected rail and LED2. Confirm no 12 V on 5 V logic rail.
5. USB + 12 V, no strips: verify no rail cross-feed.
6. One short test strip at low brightness/current limit.
7. Then J1/J2 mapping/color-order test.

## Stop conditions

Stop immediately if any of these are true:

- 12 V rail has continuity to 5 V logic rail.
- U1 pins 3 and 6 are continuous to each other.
- ESP32 VIN receives voltage from 12 V system with USB unplugged.
- LED strip current returns through ESP32/breadboard ground wiring.
- RP1/D1/fuse holder/wires become warm during low-brightness test.
