# Breadboard Wiring + Continuity Checklist — ESP32 LED Controller v6

## Physical layout rule

- Left/off-board: 12 V PSU, fuse, reverse-polarity block, LED current bus, J1/J2 V+/GND.
- Right/breadboard: ESP32, AHCT125, decoupling, data resistors, LEDs.
- Only one low-current ground reference jumper connects breadboard GND to the high-current power ground bus.

## Breadboard wiring table

| Step | Connect | To | Notes |
|---:|---|---|---|
| 1 | ESP32 GND | breadboard GND rail | Low-current logic reference |
| 2 | POWER_GND_BUS | breadboard GND rail | Single reference jumper; not load return |
| 3 | ESP32 VIN/5V | U1 pin 14 | Label `5V_FROM_USB_DO_NOT_BACKFEED` |
| 4 | U1 pin 7 | breadboard GND | AHCT ground |
| 5 | C2 0.1 µF | U1 pin 14 ↔ U1 pin 7 | Physically closest cap |
| 6 | C3 10 µF | 5 V logic ↔ GND | Nearby bulk/local cap |
| 7 | U1 pin 1 | GND | Enable buffer 1 |
| 8 | U1 pin 4 | GND | Enable buffer 2 |
| 9 | U1 pin 10 | 5 V logic | Disable unused buffer 3 |
| 10 | U1 pin 13 | 5 V logic | Disable unused buffer 4 |
| 11 | U1 pin 9 | GND | Unused input 3A |
| 12 | U1 pin 12 | GND | Unused input 4A |
| 13 | U1 pin 8 | NC | Do not connect |
| 14 | U1 pin 11 | NC | Do not connect |
| 15 | ESP32 GPIO25 | U1 pin 2 | J1 data input |
| 16 | U1 pin 3 | R1 470 Ω → J1 DATA | Keep separate from pin 6 |
| 17 | ESP32 GPIO26 | U1 pin 5 | J2 data input |
| 18 | U1 pin 6 | R2 470 Ω → J2 DATA | Keep separate from pin 3 |
| 19 | ESP32 GPIO27 | R3 220 Ω → LED1 anode | LED1 cathode to GND |
| 20 | P12_PROTECTED | R4 1 kΩ → LED2 anode | LED2 cathode to power GND |
| 21 | P12_PROTECTED | C1+ and J1/J2 V+ | Off-breadboard/high-current wiring |
| 22 | POWER_GND_BUS | C1− and J1/J2 GND | Off-breadboard/high-current wiring |



## Full-circuit breadboard prototype rule

You can prototype the **entire functional circuit** on the bench, including a real LED output, but not the full-power installation path through solderless breadboard rails.

Verified constraint:

- A known BusBoard BB830-style solderless breadboard is rated 36 V / 2 A.
- Your install-side fuse is 7.5 A and the Mean Well RS-150-12 can supply 12.5 A.
- Therefore the full LED V+/GND current path is **not** breadboard-safe at install current.

Approved breadboard LED-path options:

1. **Tiny LED load on breadboard:** one short WS2811 segment / a few pixels, bench supply current limit ≤0.5 A preferred, absolute ceiling 1 A unless the exact breadboard is known/rated and kept cool.
2. **Full logic on breadboard + LED power off-board:** keep ESP32/AHCT/data on breadboard; route LED V+ and LED ground through WAGO/terminal blocks/fuse holder/wire, with only a low-current common-ground reference to breadboard.
3. **Dummy load test:** test LED2/protected rail with a resistor load instead of strip current.

Do not feed the breadboard from the RS-150-12 behind a 7.5 A fuse unless an additional local current limit/fuse of ≤0.5–1 A is inserted for the breadboard section.

## Continuity checks, all power disconnected

### Must read ~0 Ω

- J3+ / F1 output → RP1 input.
- RP1 output → C1+ → J1 V+ → J2 V+ → R4 top.
- PSU− / J3− / POWER_GND_BUS → C1− → J1 GND → J2 GND.
- POWER_GND_BUS → ESP32 GND → U1 pin 7.
- ESP32 VIN/USB 5 V → U1 pin 14 → C2+ → C3+.
- U1 pin 1 and pin 4 → GND.
- U1 pin 9 and pin 12 → GND.
- U1 pin 10 and pin 13 → 5 V logic.
- GPIO25 → U1 pin 2 only.
- GPIO26 → U1 pin 5 only.
- GPIO27 → R3 input only.

### Must read expected resistance

- U1 pin 3 → J1 DATA: ~470 Ω through R1.
- U1 pin 6 → J2 DATA: ~470 Ω through R2.
- P12_PROTECTED → LED2 anode path: ~1 kΩ plus LED diode behavior depending meter polarity.
- GPIO27 → LED1 anode path: ~220 Ω plus LED diode behavior depending meter polarity.

### Must read open / megaohms / no continuity

- P12_PROTECTED ↔ P5_LOGIC_USB.
- P12_PROTECTED ↔ ESP32 VIN.
- U1 pin 3 ↔ U1 pin 6.
- J1 DATA ↔ J2 DATA.
- Any DATA line ↔ P12_PROTECTED.
- Any DATA line ↔ GND, except through external strip input if connected.
- U1 pin 8 and pin 11 to every rail: NC.

## Powered checks

### USB only

- U1 pin 14 to pin 7: about 5 V.
- ESP32 3V3 pin: about 3.3 V.
- P12_PROTECTED: 0 V.
- LED1 obeys firmware status blink.

### 12 V only, no USB, no strips

- P12_PROTECTED to POWER_GND_BUS: about 12 V minus reverse-protection drop, or about 12 V for MOSFET ideal diode.
- P5_LOGIC_USB: 0 V or floating near 0 V, not powered.
- ESP32 VIN: not backfed.
- LED2 on.

### USB + 12 V, no strips

- U1 pin 14 remains about 5 V.
- P12_PROTECTED remains about 12 V.
- P12_PROTECTED and P5_LOGIC_USB remain isolated.
- No heating at fuse/protection/wiring.

### One short strip, current-limited

- Set firmware global brightness limit ≤20% and max frame brightness ≤50%.
- Test J1 only, then J2 only.
- Confirm color order.
- Measure current and touch-test fuse holder, RP1, wires/connectors after 2–5 minutes.
