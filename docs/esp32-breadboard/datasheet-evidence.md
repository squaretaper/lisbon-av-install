# Datasheet Evidence — ESP32 LED Controller

Generated: 2026-05-20T16:19:02

All URLs below were HTTP-checked and local copies were saved under `inputs/datasheets/` where accessible.

## SN74AHCT125 / 74AHCT125

Source: Texas Instruments SNx4AHCT125 datasheet
URL: https://www.ti.com/lit/ds/symlink/sn74ahct125.pdf
Local: `inputs/datasheets/ti-sn74ahct125.pdf`

Relevant facts:
- AHCT125 inputs are TTL-voltage compatible.
- Recommended VCC is 4.5 V to 5.5 V.
- Recommended VIH is 2.0 V minimum and VIL is 0.8 V maximum.
- Recommended high/low output current is ±8 mA; absolute continuous output current is ±25 mA.
- All unused inputs must be held at VCC or GND.
- OE is active-low: OE low passes A to Y; OE high puts output high-impedance.

## 74AHC/74AHCT125 alternate vendor check

Source: Nexperia 74AHC125;74AHCT125 datasheet
URL: https://assets.nexperia.com/documents/data-sheet/74AHC_AHCT125.pdf
Local: `inputs/datasheets/nexperia-74ahc-ahct125.pdf`

Relevant facts:
- 74AHCT125 uses TTL input levels; 74AHC125 uses CMOS input levels.
- Inputs are over-voltage tolerant to 5.5 V.
- OE high = high impedance output; OE low = enabled output.

## ESP32 MCU / ESP32 DevKitC reference

Source: Espressif ESP32 Series Datasheet + ESP32-DevKitC docs
URL: https://www.espressif.com/sites/default/files/documentation/esp32_datasheet_en.pdf ; https://docs.espressif.com/projects/esp-idf/en/latest/esp32/hw-reference/esp32/get-started-devkitc.html
Local: `inputs/datasheets/espressif-esp32-datasheet.pdf ; inputs/datasheets/espressif-esp32-devkitc-doc.html`

Relevant facts:
- ESP32 GPIO25, GPIO26, GPIO27 are general-purpose pins on the ESP32 pin list and not boot strapping pins used in this design.
- ESP32 GPIO high output is 3.3 V-domain logic; direct 3.3 V data is marginal for many 5 V WS2811 inputs, hence AHCT level shift.
- ESP32 datasheet DC characteristics list GPIO source current up to about 40 mA at max drive strength and sink current about 28 mA; status LED at ~6 mA is conservative.
- Use USB-derived 5 V/VIN only as the AHCT125 logic supply in this design; do not inject external 5 V into VIN without re-reviewing the exact DevKit power path.

## Mean Well RS-150-12 PSU

Source: Mean Well RS-150 specification
URL: https://www.meanwell.com/Upload/PDF/RS-150/RS-150-SPEC.PDF
Local: `inputs/datasheets/meanwell-rs-150-spec.pdf`

Relevant facts:
- RS-150-12 is 12 V, 12.5 A current range, 150 W rated power.
- 12 V output adjustment range is listed as 11.4 V to 13.2 V.
- A 7.5 A DC fuse is below PSU max current but still too high to protect a 3 A 1N5822 diode.

## 1N5822 Schottky diode

Source: Vishay 1N5820/1N5821/1N5822 datasheet
URL: https://www.vishay.com/docs/88526/1n5820.pdf
Local: `inputs/datasheets/vishay-1n5820-1n5822.pdf`

Relevant facts:
- 1N5822 is a 40 V Schottky barrier plastic rectifier in the 1N5820-1N5822 family.
- Maximum average forward rectified current IF(AV) is 3.0 A at 0.375 in lead length and TL = 95 °C.
- Maximum instantaneous forward voltage for 1N5822 is 0.525 V at 3.0 A and 0.950 V at 9.4 A, pulse test.
- Typical thermal resistance listed: RθJA 40 °C/W and RθJL 10 °C/W under specified mounting conditions.
- Conclusion: not acceptable as the only full-current reverse-protection device behind a 7.5 A fuse.

## WS2811 LED driver input

Source: Worldsemi WS2811 datasheet mirror hosted by Adafruit
URL: https://cdn-shop.adafruit.com/datasheets/WS2811.pdf
Local: `inputs/datasheets/worldsemi-ws2811-adafruit-mirror.pdf`

Relevant facts:
- Electrical characteristics table specifies VDD = 4.5 V to 5.5 V for logic characteristics.
- DIN/SET VIH minimum is 0.7 × VDD and VIL maximum is 0.3 × VDD.
- For a 5 V WS2811 logic domain, VIH is about 3.5 V; ESP32 3.3 V direct drive is therefore not guaranteed.
- Using AHCT125 at 5 V gives a proper 5 V data signal for DIN.
- Reset low time is listed as above 50 µs.

## Calculation notes

- GPIO27 red status LED current estimate with 220 Ω and Vf≈2.0 V: `5.9 mA`; resistor power `7.7 mW`.
- 12 V green power LED current estimate with 1 kΩ and Vf≈2.1 V: `9.9 mA`; resistor power `98.0 mW`; use at least 1/4 W resistor.
- 470 Ω data resistor limits a hard short from 5 V data to ground to about `10.6 mA`; this is a fault-limiting aid, not permission to short data lines.
- 1N5822 dissipation at 3 A using 0.525 V datasheet point: `1.58 W`.
- 1N5822 dissipation at 7.5 A using 0.7 V rough hot-current estimate: `5.25 W`; this is far beyond casual breadboard/perfboard thermal comfort.

## Solderless breadboard current rating reference

Source: BusBoard Prototype Systems BB830 / BB830T solderless breadboard datasheet mirror
URL: https://static.datasheets.com/doc/27316152-busboard-bb830t-ds.pdf
Local: `inputs/datasheets/busboard-bb830-breadboard-datasheet.pdf`

Relevant facts:
- BB830 family datasheet lists the breadboard rating as 36 V, 2 A.
- That is a best-case rating for a known-quality board, not a blanket rating for random solderless breadboards or clone power rails.
- The Lisbon PSU/fuse design is 12 V with a 7.5 A fuse and a PSU capable of 12.5 A, so the full LED power path exceeds this breadboard reference rating.
- A full circuit prototype is fine only if the LED load is deliberately current-limited below the breadboard rating; for unknown/generic boards use a much lower comfort limit, preferably ≤0.5 A.
