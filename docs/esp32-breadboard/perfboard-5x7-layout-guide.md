# 5 cm x 7 cm Perfboard Layout Guide — ESP32 LED Controller v6

Source schematic/netlist: `esp32-led-controller-v6-standard`, KiCad 10.0.3. Board is roughly 20 × 28 holes at 2.54 mm pitch, depending edge margin.

## Recommendation

Do **not** wing the electrical topology. Use KiCad/the schematic as the net checklist, but do the physical perfboard routing manually on a 2.54 mm grid. KiCad autoroute is not useful for one-off perfboard; a simple grid placement/paper plan is better.

## Partition the board

Use three zones:

1. **Logic zone** — ESP32 socket/header, SN74AHCT125N, C2/C3, R1/R2/R3, status LED.
2. **Connector edge** — J1/J2 data/GND/V+ headers/terminal blocks facing outward for strain relief.
3. **Power/current zone** — 12 V input, fuse/reverse protection/strip V+ and strip GND. Keep high current off skinny perfboard traces; use rated wire or terminal/WAGO/bus wiring.

Keep 12 V and 5 V physically separated. Common ground is intentional, but LED strip load return should not flow through the ESP32/header/signal ground wiring.

## Suggested physical placement

- Put the ESP32 DevKit on female headers if possible, USB port hanging off the board edge.
- Put U1 SN74AHCT125N close to the ESP32 GPIO side and close to the J1/J2 data connector edge.
- Put C2 0.1 µF directly across U1 pin 14 and pin 7 on the underside if possible.
- Put C3 10 µF nearby across 5 V logic and GND; electrolytic + to 5 V, − to GND.
- Put R1/R2 470 Ω physically near the J1/J2 data connectors, after U1 output pins.
- Put LED1/R3 where visible from the top.
- Put LED2/R4 near the 12 V input/output area.
- Put C1 1000 µF at the 12 V strip power connector, not near ESP32 logic. + to 12 V protected, − to power/common ground.

## Critical nets from audited schematic

- `P5_LOGIC_USB`: ESP32 VIN/5V → U1 pin 14 → C2/C3 + → U1 pins 10 and 13 for unused OE disable.
- `GND_COMMON`: ESP32 GND → U1 pin 7 → C2/C3 − → U1 pins 1 and 4 OE enable → U1 pins 9 and 12 unused inputs → common ground reference.
- `GPIO25_TO_U1_1A`: ESP32 GPIO25 → U1 pin 2.
- `U1_1Y_TO_R1` / `J1_DATA`: U1 pin 3 → R1 470 Ω → J1 DATA.
- `GPIO26_TO_U1_2A`: ESP32 GPIO26 → U1 pin 5.
- `U1_2Y_TO_R2` / `J2_DATA`: U1 pin 6 → R2 470 Ω → J2 DATA.
- `GPIO27_STATUS`: ESP32 GPIO27 → R3 220 Ω → LED1 anode; LED1 cathode → GND.
- `P12_PROTECTED`: 12 V protected/fused → C1 + → J1/J2 V+ → R4 1 kΩ → LED2 anode.
- `P12_GND/GND_COMMON`: PSU − / power ground → C1 − → J1/J2 GND → low-current reference to logic GND.

## SN74AHCT125N DIP-14 top view

```text
          notch
      .-----------.
 /OE1 |1        14| VCC / 5V_LOGIC
  1A  |2        13| /OE4 -> 5V_LOGIC disabled
  1Y  |3        12| 4A   -> GND unused input
 /OE2 |4        11| 4Y   NC
  2A  |5        10| /OE3 -> 5V_LOGIC disabled
  2Y  |6         9| 3A   -> GND unused input
 GND  |7         8| 3Y   NC
      '-----------'
```

Used channels:
- Pin 1 `/OE1` to GND, pin 2 from GPIO25, pin 3 to R1/J1 DATA.
- Pin 4 `/OE2` to GND, pin 5 from GPIO26, pin 6 to R2/J2 DATA.

Unused channels:
- Pin 10 `/OE3` and pin 13 `/OE4` to 5 V.
- Pin 9 and pin 12 to GND.
- Pin 8 and pin 11 no-connect.

## Jumper/bus practices

- Use solid 22–24 AWG tinned copper for short logic jumpers; keep them flat to the board.
- Color code if possible: red = 12 V, orange/yellow = 5 V, black = GND, blue/green/white = signals.
- Prefer straight orthogonal runs over diagonal spaghetti.
- Put insulated jumpers on top; use bare/tinned bus links only on underside where they cannot touch.
- After soldering any bus, inspect under magnification for solder bridges between adjacent pads.
- Use heat shrink or insulation where any 12 V wire crosses logic or data.
- Anchor off-board wires with zip-tie holes/hot glue/strain relief; do not let connector solder joints carry tug force.
- Do not run LED strip current through thin Dupont wires or skinny perfboard copper. For strip V+/GND use heavier wire and terminal/WAGO distribution.

## Grounding rule

Use one common ground system electrically, but route currents intentionally:

```text
PSU − / strip GND / C1 −  === heavy current ground bus === strip returns
                         |
                         +-- one short logic-reference jumper --> ESP32 GND / U1 pin 7
```

Avoid this:

```text
strip GND return current -> ESP32 GND pin/header -> tiny logic jumper -> PSU −
```

## Pre-power continuity checks

All power disconnected:

Must be near 0 Ω:
- ESP32 GND → U1 pin 7 → common ground reference.
- ESP32 VIN/5V → U1 pin 14.
- U1 pin 1 and pin 4 → GND.
- U1 pin 10 and pin 13 → 5 V.
- U1 pin 9 and pin 12 → GND.
- GPIO25 → U1 pin 2 only.
- GPIO26 → U1 pin 5 only.

Must be expected resistance:
- U1 pin 3 → J1 DATA: about 470 Ω via R1.
- U1 pin 6 → J2 DATA: about 470 Ω via R2.
- GPIO27 → LED1 path: about 220 Ω plus diode behavior.
- 12 V protected → LED2 path: about 1 kΩ plus diode behavior.

Must be open/no continuity:
- 12 V protected ↔ 5 V logic.
- 12 V protected ↔ ESP32 VIN.
- DATA lines ↔ 12 V.
- J1 DATA ↔ J2 DATA.
- U1 pin 8 and pin 11 ↔ every rail.

## Bring-up order

1. USB only, no 12 V, no strip: ESP32 boots, U1 has 5 V, status LED firmware works.
2. 12 V only, no USB/strip: LED2 power-good works; 5 V/ESP32 not backfed.
3. USB + 12 V, no strip: 5 V and 12 V remain isolated except ground.
4. Attach one short strip to J1 with known-safe firmware/current behavior.
5. Only after stable: test J2 or longer loads.
