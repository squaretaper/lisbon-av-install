#include <Arduino.h>
#include <FastLED.h>

// Hardware map from audited schematic:
// ESP32 GPIO25 -> U1 pin 2 / 1A -> U1 pin 3 / 1Y -> R1 470R -> J1 DATA.
// ESP32 GPIO26 -> U1 pin 5 / 2A -> U1 pin 6 / 2Y -> R2 470R -> J2 DATA.
// ESP32 GPIO27 -> R3 220R -> status LED anode, LED cathode -> GND.
static constexpr uint8_t J1_DATA_PIN = 25;
static constexpr uint8_t J2_DATA_PIN = 26;
static constexpr uint8_t STATUS_LED_PIN = 27;

// Safe bench defaults: low brightness and short logical chain.
// If the physical strip is shorter, extra pixels are just ignored by the strip.
static constexpr uint16_t NUM_LEDS = 12;
static constexpr uint8_t BRIGHTNESS = 24;  // ~9% of max; keeps current modest.
static constexpr uint16_t STEP_MS = 700;

CRGB leds[NUM_LEDS];

void statusPulse(uint8_t count, uint16_t ms) {
  for (uint8_t i = 0; i < count; ++i) {
    digitalWrite(STATUS_LED_PIN, HIGH);
    delay(ms);
    digitalWrite(STATUS_LED_PIN, LOW);
    delay(ms);
  }
}

void fillAndShow(const CRGB& color, const char* label) {
  fill_solid(leds, NUM_LEDS, color);
  FastLED.show();
  Serial.print("J1 strip test: ");
  Serial.println(label);
  statusPulse(1, 80);
  delay(STEP_MS);
}

void chase(const CRGB& color, const char* label) {
  Serial.print("J1 strip chase: ");
  Serial.println(label);
  for (uint16_t i = 0; i < NUM_LEDS; ++i) {
    fill_solid(leds, NUM_LEDS, CRGB::Black);
    leds[i] = color;
    FastLED.show();
    digitalWrite(STATUS_LED_PIN, (i % 2) == 0 ? HIGH : LOW);
    delay(180);
  }
  digitalWrite(STATUS_LED_PIN, LOW);
}

void setup() {
  Serial.begin(115200);
  delay(300);

  pinMode(STATUS_LED_PIN, OUTPUT);
  pinMode(J2_DATA_PIN, OUTPUT);
  digitalWrite(J2_DATA_PIN, LOW);  // keep unused output quiet for this J1 test

  // Color order from breadboarded J1 test: BRG gives correct physical red/green/blue.
  FastLED.addLeds<WS2811, J1_DATA_PIN, BRG>(leds, NUM_LEDS);
  FastLED.setBrightness(BRIGHTNESS);
  FastLED.clear(true);

  Serial.println();
  Serial.println("ESP32 Lisbon J1 WS2811 strip test");
  Serial.println("Path: GPIO25 -> AHCT125 U1 pin2/3 -> R1 470R -> J1 DATA");
  Serial.println("Pattern: off, red, green, blue, white, moving red pixel. Low brightness.");

  statusPulse(3, 100);
  delay(500);
}

void loop() {
  FastLED.clear(true);
  Serial.println("J1 strip test: OFF");
  delay(900);

  fillAndShow(CRGB::Red, "ALL RED");
  fillAndShow(CRGB::Green, "ALL GREEN");
  fillAndShow(CRGB::Blue, "ALL BLUE");
  fillAndShow(CRGB(32, 32, 32), "DIM WHITE");
  chase(CRGB::Red, "RED PIXEL WALK");
}
