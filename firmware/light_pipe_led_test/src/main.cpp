#include <Arduino.h>

// Lisbon AV case light-pipe LED test.
// Physical order from bottom -> top = GPIO13, GPIO14, GPIO32, GPIO33.
// Each LED/light-pipe path must have its own current-limiting resistor in series.
// Expected wiring: GPIO -> resistor -> LED anode; LED cathode -> GND.
static constexpr uint8_t LED_BOTTOM = 13;
static constexpr uint8_t LED_LOW_MID = 14;
static constexpr uint8_t LED_HIGH_MID = 32;
static constexpr uint8_t LED_TOP = 33;

// Existing outputs kept quiet during this discrete-LED test.
static constexpr uint8_t STRIP_J1_DATA = 25;
static constexpr uint8_t STRIP_J2_DATA = 26;
static constexpr uint8_t STATUS_LED = 27;

struct LightPipeLed {
  uint8_t pin;
  const char* name;
};

static constexpr LightPipeLed LIGHT_PIPE[] = {
  {LED_BOTTOM, "bottom / GPIO13"},
  {LED_LOW_MID, "lower-mid / GPIO14"},
  {LED_HIGH_MID, "upper-mid / GPIO32"},
  {LED_TOP, "top / GPIO33"},
};

static constexpr uint8_t LED_COUNT = sizeof(LIGHT_PIPE) / sizeof(LIGHT_PIPE[0]);
static constexpr uint16_t STEP_MS = 650;
static constexpr uint16_t GAP_MS = 120;

void allLightPipe(uint8_t level) {
  for (const auto& led : LIGHT_PIPE) {
    digitalWrite(led.pin, level);
  }
}

void statusPulse(uint8_t count) {
  for (uint8_t i = 0; i < count; ++i) {
    digitalWrite(STATUS_LED, HIGH);
    delay(70);
    digitalWrite(STATUS_LED, LOW);
    delay(70);
  }
}

void showOne(uint8_t idx) {
  allLightPipe(LOW);
  digitalWrite(LIGHT_PIPE[idx].pin, HIGH);
  Serial.print("ON: ");
  Serial.println(LIGHT_PIPE[idx].name);
  statusPulse(1);
  delay(STEP_MS);
  digitalWrite(LIGHT_PIPE[idx].pin, LOW);
  delay(GAP_MS);
}

void setup() {
  Serial.begin(115200);
  delay(300);

  pinMode(STRIP_J1_DATA, OUTPUT);
  pinMode(STRIP_J2_DATA, OUTPUT);
  pinMode(STATUS_LED, OUTPUT);
  digitalWrite(STRIP_J1_DATA, LOW);
  digitalWrite(STRIP_J2_DATA, LOW);
  digitalWrite(STATUS_LED, LOW);

  for (const auto& led : LIGHT_PIPE) {
    pinMode(led.pin, OUTPUT);
    digitalWrite(led.pin, LOW);
  }

  Serial.println();
  Serial.println("Lisbon AV light-pipe discrete LED test");
  Serial.println("Expected physical order bottom -> top:");
  Serial.println("  GPIO13, GPIO14, GPIO32, GPIO33");
  Serial.println("Pattern: bottom-to-top chase, top-to-bottom chase, all-on blink.");
  Serial.println("STOP if any LED path lacks a series resistor or anything gets warm.");

  statusPulse(3);
}

void loop() {
  Serial.println("CHASE: bottom -> top");
  for (uint8_t i = 0; i < LED_COUNT; ++i) {
    showOne(i);
  }

  Serial.println("CHASE: top -> bottom");
  for (int8_t i = LED_COUNT - 1; i >= 0; --i) {
    showOne(static_cast<uint8_t>(i));
  }

  Serial.println("ALL ON");
  allLightPipe(HIGH);
  digitalWrite(STATUS_LED, HIGH);
  delay(900);

  Serial.println("ALL OFF");
  allLightPipe(LOW);
  digitalWrite(STATUS_LED, LOW);
  delay(900);
}
