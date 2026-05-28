# Hardware + Electrical — ESP32, PSU, LEDs

## Controller purpose

The ESP32 controller receives light frames from the server over WiFi/WebSocket and drives two 12 V WS2811-style LED outputs:

- J1: V+, GND, DATA
- J2: V+, GND, DATA

It is not responsible for audio or CV.

## Power topology

```text
12 V LED power:
PSU + → source-side fuse → board input J3+ → reverse-polarity protection → protected 12 V rail → J1/J2 V+
PSU − → common ground → J1/J2 GND

5 V logic power:
USB-C → ESP32 DevKit → VIN/5V_FROM_USB_DO_NOT_BACKFEED → AHCT125 VCC

Signal reference:
PSU −, ESP32 GND, AHCT125 GND, LED strip GND all tied to common ground.
```

## Critical rail rule

The 12 V protected rail and the USB-derived 5 V logic rail are separate rails.

- 12 V rail: D1 cathode / C1+ / J1 V+ / J2 V+ / LED2 anode side.
- 5 V rail: ESP32 VIN/5V / AHCT125 pin 14 / C2+ / C3+.
- Shared node: ground only.

A continuity check that finds 12 V rail ↔ 5 V rail as ~0 Ω indicates a wiring error.

## Reverse-polarity protection correction

The source schematic used 1N5822 as D1. That is acceptable only for small loads. It is not a good final choice if all LED strip current flows through it.

Why:

- 1N5822 is a 3 A-class Schottky.
- The planned fuse is 7.5 A.
- Mean Well RS-150-12 can supply roughly 12.5 A.
- At several amps the diode may dissipate multiple watts, which is too much for casual perfboard/enclosure use.

v6 recommendation:

1. Prefer a P-channel MOSFET / ideal-diode reverse-polarity circuit for the LED 12 V rail; or
2. Use a high-current rectifier/Schottky rated above the fuse current with a real thermal path; or
3. Lower the fuse so it actually protects the diode and downstream wiring.

Do not document “1N5822 at 6 A is irrelevant” as final-build truth.

## Fuse placement

- The DC fuse should be as close to the PSU positive output/source as practical.
- The fuse protects downstream wiring and the board.
- Any long positive lead before the fuse is unfused and should be avoided.
- AC-side fused C14 inlet is separate and does not replace DC-side protection.

## Wire and connector notes

- Size LED power wiring for expected current and enclosure heat.
- Do not push full strip current through marginal JST-SM pigtails if they are not rated for it.
- Consider power injection near LED strips for long runs.
- Keep data and ground paired; the data line needs a nearby reference.

## AHCT125 level shifter

Use SN74AHCT125N or equivalent AHCT/HCT-family buffer powered at 5 V.

Pin plan:

| Pin | Name | Connection |
|---:|---|---|
| 1 | /OE1 | GND |
| 2 | 1A | ESP32 GPIO25 |
| 3 | 1Y | R1 470 Ω → J1 DATA |
| 4 | /OE2 | GND |
| 5 | 2A | ESP32 GPIO26 |
| 6 | 2Y | R2 470 Ω → J2 DATA |
| 7 | GND | common ground |
| 8 | 3Y | unconnected |
| 9 | 3A | GND |
| 10 | /OE3 | 5 V logic/VCC |
| 11 | 4Y | unconnected |
| 12 | 4A | GND |
| 13 | /OE4 | 5 V logic/VCC |
| 14 | VCC | ESP32 VIN/USB-derived 5 V |

Notes:

- `/OE` is active-low. Tying unused OEs high disables unused buffers 3/4, leaving pins 8 and 11 high-Z. This matches the breadboard checklist and build plan.
- Do not leave AHCT inputs floating.
- Do not substitute plain HC125 unless input-high thresholds are verified with ESP32 3.3 V logic at 5 V VCC.

## Decoupling and bulk caps

- C1: 1000 µF / 25 V across protected 12 V rail and ground, near LED power output/input.
- C2: 0.1 µF ceramic directly across AHCT125 pin 14 to pin 7, leads as short as possible.
- C3: 10 µF near AHCT125 VCC/GND for local logic reservoir.

## ESP32 power rule

ESP32 is USB-C powered only.

Label the VIN node:

```text
5V_FROM_USB_DO_NOT_BACKFEED
```

Never connect external 5 V into VIN for this build unless the exact DevKit power path has been re-reviewed.

## Case light-pipe LED GPIOs

Four additional discrete case/light-pipe indicators are direct ESP32 GPIO outputs, active high. Physical order from bottom to top of the light pipe:

| Physical position | GPIO | Expected wiring |
|---|---:|---|
| bottom | GPIO13 | GPIO13 → series resistor → LED anode; LED cathode → GND |
| lower-mid | GPIO14 | GPIO14 → series resistor → LED anode; LED cathode → GND |
| upper-mid | GPIO32 | GPIO32 → series resistor → LED anode; LED cathode → GND |
| top | GPIO33 | GPIO33 → series resistor → LED anode; LED cathode → GND |

Use one current-limiting resistor per LED/light-pipe path. The existing GPIO27 status LED uses R3 = 220 Ω and was visually bright; use 220 Ω for matching punchy indicators, or 470 Ω–1 kΩ for a softer diffused glow.

Bench firmware for this mapping lives at `firmware/light_pipe_led_test/` and chases bottom→top, top→bottom, then all-on/all-off while holding strip data GPIO25/GPIO26 low.

## Pre-power continuity checklist

With PSU disconnected, USB disconnected, and ICs out of sockets where practical:

### 12 V path

- J3+ → reverse-protection input/anode: ~0 Ω.
- Reverse-protection output/cathode → C1+ → J1 V+ → J2 V+: ~0 Ω.
- J1/J2 V+ → GND: open/charging behavior through C1, not a hard short.
- Reverse-protection diode-test: forward drop from input to protected rail; open reverse.

### 5 V path

- ESP32 VIN/5V → AHCT125 pin 14 → C2/C3 positive: ~0 Ω.
- ESP32 VIN/5V → GND: not a hard short.
- 5 V logic rail → 12 V protected rail: open / megaohms.

### Ground

- PSU− / J3− / C1− / ESP32 GND / AHCT125 pin 7 / J1 GND / J2 GND / LED cathodes: ~0 Ω.

### Signal

- GPIO25 → AHCT125 pin 2 only.
- GPIO26 → AHCT125 pin 5 only.
- GPIO13 → its own light-pipe LED series resistor/input only; no continuity to 5 V, 12 V, J1/J2 DATA, or another GPIO.
- GPIO14 → its own light-pipe LED series resistor/input only; no continuity to 5 V, 12 V, J1/J2 DATA, or another GPIO.
- GPIO32 → its own light-pipe LED series resistor/input only; no continuity to 5 V, 12 V, J1/J2 DATA, or another GPIO.
- GPIO33 → its own light-pipe LED series resistor/input only; no continuity to 5 V, 12 V, J1/J2 DATA, or another GPIO.
- AHCT125 pin 3 → R1 → J1 DATA: ~470 Ω.
- AHCT125 pin 6 → R2 → J2 DATA: ~470 Ω.
- DATA lines → 12 V or GND: open, not shorted.
- AHCT125 pins 1, 4, 9, 12 → GND: ~0 Ω.
- AHCT125 pins 10, 13 → 5 V logic/VCC: ~0 Ω.
- AHCT125 pins 8 and 11: unconnected.

## Power-up sequence

1. USB only: ESP32 boots; AHCT125 VCC reads ~5 V; no 12 V appears on J1/J2 V+.
2. 12 V only/no strips: green power LED lights; protected 12 V rail reads expected PSU minus protection drop; D1/MOSFET area stays cool.
3. USB + 12 V/no strips: ESP32 connects to server; no rail cross-feed.
4. Connect short test strip at low brightness.
5. Increase current gradually while checking fuse holder, wiring, reverse-protection device, PSU, and enclosure temperature.
