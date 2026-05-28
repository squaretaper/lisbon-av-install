#include <Arduino.h>

static constexpr int STATUS_LED = 27;  // GPIO27 -> 220R -> LED anode, LED cathode -> GND
static constexpr int DATA_OUT_1 = 25;  // AHCT125 channel 1 input
static constexpr int DATA_OUT_2 = 26;  // AHCT125 channel 2 input

void pulseStatus(int count, int onMs, int offMs) {
  for (int i = 0; i < count; ++i) {
    digitalWrite(STATUS_LED, HIGH);
    delay(onMs);
    digitalWrite(STATUS_LED, LOW);
    delay(offMs);
  }
}

void setup() {
  Serial.begin(115200);
  delay(300);

  pinMode(STATUS_LED, OUTPUT);
  pinMode(DATA_OUT_1, OUTPUT);
  pinMode(DATA_OUT_2, OUTPUT);

  // Keep LED data lines quiet for this bench test.
  digitalWrite(DATA_OUT_1, LOW);
  digitalWrite(DATA_OUT_2, LOW);

  Serial.println();
  Serial.println("ESP32 Lisbon status LED test firmware");
  Serial.println("GPIO27 should blink: three quick pulses, then steady 1 Hz blink.");

  pulseStatus(3, 120, 120);
}

void loop() {
  digitalWrite(STATUS_LED, HIGH);
  Serial.println("GPIO27 HIGH / status LED ON");
  delay(500);

  digitalWrite(STATUS_LED, LOW);
  Serial.println("GPIO27 LOW / status LED OFF");
  delay(500);
}
