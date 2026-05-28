#include <Arduino.h>
#include <FastLED.h>

// Red-only organic/strobe/chase blend for J1, with live serial controls.
// Hardware path: ESP32 GPIO25 -> AHCT125 U1 pin2/3 -> R1 470R -> J1 DATA.
// J2/GPIO26 is held LOW. GPIO27 is the local status LED.
static constexpr uint8_t J1_DATA_PIN = 25;
static constexpr uint8_t J2_DATA_PIN = 26;
static constexpr uint8_t STATUS_LED_PIN = 27;

// Extra logical LEDs are ignored if the strip is shorter.
static constexpr uint16_t NUM_LEDS = 60;
static constexpr uint8_t MASTER_BRIGHTNESS = 255; // full brightness; pattern stays red-only
static constexpr uint8_t MAX_RED = 255;

// High refresh, slower animation layers. WS2811 timing is still the hard floor (~1.85ms for 60 nodes).
static constexpr uint8_t FRAME_DELAY_MIN_MS = 2;
static constexpr uint8_t FRAME_DELAY_MAX_MS = 10;
static constexpr uint8_t RUNNER_COUNT = 6;
static constexpr uint8_t FADE_ZONE_COUNT = 5;
static constexpr uint8_t HARD_FLASH_CHANCE = 34;

CRGB leds[NUM_LEDS];

struct Runner {
  int16_t pos256;      // pixel position in 1/256 pixel units
  int16_t speed256;    // signed movement per frame in 1/256 pixel units
  uint8_t dots;        // separated pixels in this train
  uint8_t spacing;     // empty pixels between dots
  uint8_t intensity;   // peak red level
  uint8_t phase;       // frame-skipping / stutter phase
};

struct FadeZone {
  int16_t center;      // segment center in pixel units
  int8_t drift;        // slow center drift direction
  uint8_t width;       // affected segment width
  uint8_t phase;       // fade phase 0..255
  uint8_t speed;       // fade speed per frame
  uint8_t peak;        // max red level
  uint8_t strobeLatch; // short strobe window when fade reaches peak
};

struct LiveControls {
  uint8_t brightness;   // b 0..255
  uint8_t density;      // d 0..255, number of extra events
  uint8_t strobe;       // s 0..255, peak flashes/cuts
  uint8_t chase;        // c 0..255, chase speed/rate
  uint8_t fade;         // f 0..255, fade speed / trail length
  uint8_t modeOverride; // m 0..3 locks mode, m 255 returns to auto
};

Runner runners[RUNNER_COUNT];
FadeZone zones[FADE_ZONE_COUNT];
LiveControls ctl = {255, 150, 135, 145, 130, 255};
char serialLine[72];
uint8_t serialPos = 0;

uint32_t rngState = 0xC0FFEE27UL;
uint32_t frameCounter = 0;
uint32_t lastModePrint = 0;
uint32_t modeStart = 0;
uint8_t mode = 0;

uint32_t xorshift32() {
  uint32_t x = rngState;
  x ^= x << 13;
  x ^= x >> 17;
  x ^= x << 5;
  rngState = x ? x : 0xA5A5A5A5UL;
  return rngState;
}

uint16_t randN(uint16_t n) {
  return n ? (xorshift32() % n) : 0;
}

uint8_t randByte(uint8_t lo, uint8_t hi) {
  return lo + (xorshift32() % (uint16_t)(hi - lo + 1));
}

uint8_t clampByte(int v) {
  if (v < 0) return 0;
  if (v > 255) return 255;
  return (uint8_t)v;
}

uint8_t chanceScale(uint8_t base, uint8_t control) {
  uint16_t v = (uint16_t)base * (40 + control) / 150;
  return v > 100 ? 100 : (uint8_t)v;
}

uint8_t ctlDensity(uint8_t base) {
  uint16_t v = (uint16_t)base * (40 + ctl.density) / 150;
  if (v < 1) v = 1;
  return v > 12 ? 12 : (uint8_t)v;
}

uint8_t ctlStrobe(uint8_t base) {
  return chanceScale(base, ctl.strobe);
}

uint8_t ctlFade(uint8_t base) {
  // Higher control = faster fade / shorter trails. Lower = more lingering glow.
  uint16_t v = (uint16_t)base * (45 + ctl.fade) / 150;
  if (v < 4) v = 4;
  return v > 90 ? 90 : (uint8_t)v;
}

int16_t ctlChase(int16_t speed) {
  // Higher control = faster chase. Preserves sign.
  int32_t v = (int32_t)speed * (45 + ctl.chase) / 145;
  if (v > 620) v = 620;
  if (v < -620) v = -620;
  if (v >= 0 && v < 18) v = 18;
  if (v < 0 && v > -18) v = -18;
  return (int16_t)v;
}

uint8_t activeMode() {
  return ctl.modeOverride <= 3 ? ctl.modeOverride : mode;
}

uint8_t triangleWave8(uint8_t phase) {
  uint16_t v = phase < 128 ? (uint16_t)phase * 2 : (uint16_t)(255 - phase) * 2;
  return v > 255 ? 255 : (uint8_t)v;
}

uint8_t smoothish(uint8_t v) {
  // Cheap ease-in/ease-out-ish curve without floats.
  uint16_t inv = 255 - v;
  uint16_t ii = inv * inv / 255;
  uint16_t rise = (uint16_t)v * v / 765;
  uint16_t out = 255 - ii + rise;
  return out > 255 ? 255 : (uint8_t)out;
}

int16_t wrapIndex(int16_t i) {
  while (i < 0) i += NUM_LEDS;
  while (i >= (int16_t)NUM_LEDS) i -= NUM_LEDS;
  return i;
}

int16_t clampSpeed(int16_t v) {
  if (v > 420) return 420;
  if (v < -420) return -420;
  if (v >= 0 && v < 26) return 26;
  if (v < 0 && v > -26) return -26;
  return v;
}

void addRedWrapped(int16_t i, uint8_t amount) {
  uint16_t idx = (uint16_t)wrapIndex(i);
  uint16_t v = leds[idx].r + amount;
  leds[idx] = CRGB(v > MAX_RED ? MAX_RED : v, 0, 0);
}

void setRedWrapped(int16_t i, uint8_t level) {
  uint16_t idx = (uint16_t)wrapIndex(i);
  leds[idx] = CRGB(level, 0, 0);
}

void redOnlyGuardrail() {
  for (uint16_t i = 0; i < NUM_LEDS; ++i) {
    leds[i].g = 0;
    leds[i].b = 0;
  }
}

void clearFrame() {
  fill_solid(leds, NUM_LEDS, CRGB::Black);
}

void initState();

void printControls() {
  Serial.print("controls b="); Serial.print(ctl.brightness);
  Serial.print(" d="); Serial.print(ctl.density);
  Serial.print(" s="); Serial.print(ctl.strobe);
  Serial.print(" c="); Serial.print(ctl.chase);
  Serial.print(" f="); Serial.print(ctl.fade);
  Serial.print(" m=");
  if (ctl.modeOverride <= 3) Serial.println(ctl.modeOverride);
  else Serial.println("auto");
}

void processSerialCommand(char* line) {
  while (*line == ' ' || *line == '\t') ++line;
  if (*line == 0) return;

  char cmd = *line++;
  while (*line == ' ' || *line == '\t' || *line == '=') ++line;
  int value = atoi(line);

  if (cmd == '?' || cmd == 'p') {
    printControls();
    return;
  }

  if (cmd == 'b') {
    ctl.brightness = clampByte(value);
    FastLED.setBrightness(ctl.brightness);
  } else if (cmd == 'd') {
    ctl.density = clampByte(value);
  } else if (cmd == 's') {
    ctl.strobe = clampByte(value);
  } else if (cmd == 'c') {
    ctl.chase = clampByte(value);
  } else if (cmd == 'f') {
    ctl.fade = clampByte(value);
  } else if (cmd == 'm') {
    ctl.modeOverride = (value >= 0 && value <= 3) ? (uint8_t)value : 255;
    if (ctl.modeOverride <= 3) {
      mode = ctl.modeOverride;
      modeStart = millis();
    }
  } else if (cmd == 'x') {
    clearFrame();
    FastLED.show();
  } else if (cmd == 'r') {
    initState();
  } else {
    Serial.println("commands: b/d/s/c/f 0..255, m 0..3 or 255 auto, x blackout, r reseed, ? status");
    return;
  }

  printControls();
}

void handleSerialControls() {
  while (Serial.available() > 0) {
    char ch = (char)Serial.read();
    if (ch == '\r') continue;
    if (ch == '\n') {
      serialLine[serialPos] = 0;
      processSerialCommand(serialLine);
      serialPos = 0;
    } else if (serialPos < sizeof(serialLine) - 1) {
      serialLine[serialPos++] = ch;
    } else {
      serialPos = 0;
      Serial.println("serial command too long; dropped");
    }
  }
}

void organicFadeBase() {
  // Keeps history visible: organic layers breathe instead of every frame hard-clearing.
  uint8_t m = activeMode();
  uint8_t fadeAmount = 18 + randN(10);
  if (m == 2) fadeAmount = 28 + randN(16); // more clipped/strobe mode
  if (m == 3) fadeAmount = 12 + randN(8);  // lush overlap mode
  fadeAmount = ctlFade(fadeAmount);

  for (uint16_t i = 0; i < NUM_LEDS; ++i) {
    leds[i].fadeToBlackBy(fadeAmount);
    leds[i].g = 0;
    leds[i].b = 0;
  }
}

void resetRunner(uint8_t i) {
  runners[i].pos256 = (int16_t)(randN(NUM_LEDS) * 256);
  int16_t speed = (int16_t)(35 + randN(150)); // slower than pure high-FPS sketch
  if (randN(2)) speed = -speed;
  runners[i].speed256 = speed;
  runners[i].dots = 2 + randN(5);
  runners[i].spacing = 3 + randN(9);
  runners[i].intensity = randByte(115, 245);
  runners[i].phase = randByte(0, 15);
}

void resetFadeZone(uint8_t i) {
  zones[i].center = randN(NUM_LEDS);
  zones[i].drift = randN(2) ? 1 : -1;
  zones[i].width = 4 + randN(14);
  zones[i].phase = randByte(0, 255);
  zones[i].speed = 1 + randN(5);
  zones[i].peak = randByte(120, 255);
  zones[i].strobeLatch = 0;
}

void initState() {
  for (uint8_t i = 0; i < RUNNER_COUNT; ++i) resetRunner(i);
  for (uint8_t i = 0; i < FADE_ZONE_COUNT; ++i) resetFadeZone(i);
}

void organicFadeLayer() {
  uint8_t densityGate = ctlStrobe(38);
  for (uint8_t z = 0; z < FADE_ZONE_COUNT; ++z) {
    FadeZone& f = zones[z];
    uint8_t previousPhase = f.phase;
    f.phase += 1 + ((uint16_t)f.speed * (50 + ctl.fade) / 180);

    // Very slow spatial drift, so fade regions move like living pools.
    if ((frameCounter + z * 13) % (26 + z * 7) == 0) {
      f.center = wrapIndex(f.center + f.drift);
      if (randN(100) < 8) f.drift = -f.drift;
    }
    if (randN(1000) < 7) {
      f.width = 4 + randN(15);
      f.peak = randByte(130, 255);
    }

    uint8_t wave = smoothish(triangleWave8(f.phase));
    uint8_t level = (uint8_t)((uint16_t)wave * f.peak / 255);

    // When a zone crosses into the bright part, arm a short strobe latch.
    if (previousPhase < 128 && f.phase >= 128 && randN(100) < densityGate) f.strobeLatch = 6 + randN(12);

    int16_t half = f.width / 2;
    for (int16_t o = -half; o <= half; ++o) {
      uint8_t distance = abs(o);
      uint8_t falloff = distance >= half ? 35 : 255 - (uint16_t)distance * 190 / (half + 1);
      uint8_t px = (uint8_t)((uint16_t)level * falloff / 255);
      if (px > 8) addRedWrapped(f.center + o, px);
    }
  }
}

void peakStrobeLayer() {
  // Fade-in pools become stroby near their peak, then relax back into organic fade.
  for (uint8_t z = 0; z < FADE_ZONE_COUNT; ++z) {
    FadeZone& f = zones[z];
    uint8_t wave = triangleWave8(f.phase);
    bool nearPeak = wave > 190;

    if (f.strobeLatch > 0) --f.strobeLatch;
    if (!nearPeak && f.strobeLatch == 0) continue;
    if (randN(100) > ctlStrobe(nearPeak ? 44 : 28)) continue;

    uint8_t hits = 1 + randN(ctlDensity(3));
    for (uint8_t h = 0; h < hits; ++h) {
      int16_t offset = (int16_t)randN(f.width + 1) - (int16_t)(f.width / 2);
      addRedWrapped(f.center + offset, randN(100) < ctlStrobe(HARD_FLASH_CHANCE) ? 255 : randByte(145, 240));
      if (randN(100) < ctlStrobe(30)) addRedWrapped(f.center + offset + (randN(2) ? 1 : -1), randByte(60, 190));
    }
  }
}

void slowSegmentedChaseLayer() {
  const int16_t span = (int16_t)(NUM_LEDS * 256);

  for (uint8_t i = 0; i < RUNNER_COUNT; ++i) {
    Runner& r = runners[i];

    // Slow-ish, musical chase drift; still rendered at high refresh.
    if (randN(100) < 8) r.speed256 = clampSpeed(r.speed256 + (int16_t)randN(49) - 24);
    if (randN(1000) < ctlStrobe(8)) r.speed256 = -r.speed256;
    if (randN(100) < 5) r.dots = 2 + randN(5);
    if (randN(100) < 6) r.spacing = 3 + randN(10);
    if (randN(100) < 7) r.intensity = randByte(110, 255);

    uint8_t m = activeMode();
    uint8_t moveGate = 2 + (255 - ctl.chase) / 70;
    if (((frameCounter + r.phase) % moveGate) == 0 || m == 1 || m == 2) r.pos256 += ctlChase(r.speed256);
    if (randN(1000) < ctlStrobe(8)) r.pos256 += (int16_t)((randN(13) - 6) * 256);

    while (r.pos256 < 0) r.pos256 += span;
    while (r.pos256 >= span) r.pos256 -= span;

    int16_t center = r.pos256 / 256;
    int8_t dir = r.speed256 >= 0 ? -1 : 1;
    for (uint8_t dot = 0; dot < r.dots; ++dot) {
      if (randN(100) < 16) continue;
      int16_t idx = center + dir * (int16_t)(dot * r.spacing);
      uint8_t level = (uint8_t)((uint16_t)r.intensity * (r.dots - dot) / r.dots);
      addRedWrapped(idx, level);
      if (randN(100) < 10) addRedWrapped(idx + dir, level / 3);
    }
  }
}

void flashSetLayer(uint8_t density) {
  uint8_t sets = 1 + randN(ctlDensity(density));
  for (uint8_t s = 0; s < sets; ++s) {
    if (randN(100) > ctlStrobe(45 + density * 8)) continue;
    int16_t anchor = randN(NUM_LEDS);
    int8_t dir = randN(2) ? 1 : -1;
    uint8_t dots = 1 + randN(ctlDensity(5));
    uint8_t spacing = 2 + randN(10);
    uint8_t peak = randN(100) < ctlStrobe(HARD_FLASH_CHANCE) ? 255 : randByte(115, 235);

    for (uint8_t d = 0; d < dots; ++d) {
      if (randN(100) < 20) continue;
      int16_t idx = anchor + dir * (int16_t)(d * spacing) + (int16_t)randN(3) - 1;
      uint8_t level = d == 0 ? peak : (uint8_t)((uint16_t)peak * (dots - d) / dots);
      addRedWrapped(idx, level);
    }
  }
}

void strobeCutLayer() {
  // Hard black cuts, but not constantly: intense without losing all organic fade.
  uint8_t m = activeMode();
  uint8_t chance = m == 2 ? 28 : 12;
  if (randN(100) > ctlStrobe(chance)) return;

  uint8_t cuts = 1 + randN(ctlDensity(3));
  for (uint8_t c = 0; c < cuts; ++c) {
    int16_t anchor = randN(NUM_LEDS);
    uint8_t len = 1 + randN(8);
    int8_t dir = randN(2) ? 1 : -1;
    for (uint8_t i = 0; i < len; ++i) setRedWrapped(anchor + dir * i, 0);
  }
}

void scanlineAccentLayer() {
  // Occasional code-like fast chasers over the slow organic bed.
  uint8_t m = activeMode();
  if (m == 0 && randN(100) > ctlStrobe(35)) return;
  if (m == 3 && randN(100) > ctlStrobe(55)) return;

  uint8_t lanes = m == 1 ? 4 + randN(ctlDensity(3)) : 2 + randN(ctlDensity(3));
  for (uint8_t lane = 0; lane < lanes; ++lane) {
    uint8_t clock = m == 1 ? 3 + lane + randN(5) : 6 + lane * 2 + randN(7);
    clock = 1 + ((uint16_t)clock * (300 - ctl.chase) / 255);
    int16_t base = ((frameCounter / clock) * (1 + lane) + lane * 13) % NUM_LEDS;
    int8_t dir = (lane & 1) ? -1 : 1;
    if (dir < 0) base = NUM_LEDS - 1 - base;

    uint8_t dots = 2 + randN(4);
    uint8_t spacing = 3 + randN(7);
    for (uint8_t d = 0; d < dots; ++d) {
      if (randN(100) < 18) continue;
      addRedWrapped(base - dir * (int16_t)(d * spacing), d == 0 ? 255 : randByte(80, 210));
    }
  }
}

void organicMixedIntensity() {
  uint8_t m = activeMode();
  organicFadeBase();

  // Always-on blend: different styles coexist rather than one mode replacing another.
  organicFadeLayer();
  slowSegmentedChaseLayer();
  peakStrobeLayer();
  scanlineAccentLayer();

  if (m == 0) {
    flashSetLayer(1);               // breathing / sparse
  } else if (m == 1) {
    flashSetLayer(2);               // chase-forward
    if (randN(100) < ctlStrobe(65)) scanlineAccentLayer();
  } else if (m == 2) {
    flashSetLayer(4);               // stroby/intense
    peakStrobeLayer();
    if (randN(100) < ctlStrobe(18)) clearFrame();
  } else {
    flashSetLayer(2);               // all layers, more organic overlap
    if (randN(100) < ctlStrobe(45)) slowSegmentedChaseLayer();
  }

  strobeCutLayer();
  redOnlyGuardrail();
}

void maybeAdvanceMode() {
  if (ctl.modeOverride <= 3) return;

  uint32_t elapsed = millis() - modeStart;
  if (elapsed > 4200 + randN(2200)) {
    mode = (mode + 1) % 4;
    modeStart = millis();
    if (randN(100) < ctlStrobe(35)) clearFrame();
    FastLED.show();
  }

  if (millis() - lastModePrint > 1000) {
    lastModePrint = millis();
    Serial.print("red organic strobe blend mode ");
    Serial.print(activeMode());
    Serial.print(" / ");
    uint8_t m = activeMode();
    if (m == 0) Serial.println("fade pools + sparse chase");
    else if (m == 1) Serial.println("slow chases + scanline accents");
    else if (m == 2) Serial.println("fade peaks become strobes");
    else Serial.println("mixed organic intensity");
  }
}

void setup() {
  Serial.begin(115200);
  delay(250);

  // Mix in an unconnected-ish analog read if available; harmless if not random.
  rngState ^= (uint32_t)analogRead(34) << 16;
  rngState ^= micros();

  pinMode(STATUS_LED_PIN, OUTPUT);
  pinMode(J2_DATA_PIN, OUTPUT);
  digitalWrite(J2_DATA_PIN, LOW);

  // Observed mapping: RGB made CRGB::Red physically blue; BGR made it green.
  // That means this strip wants the red component in byte 2: BRG.
  FastLED.addLeds<WS2811, J1_DATA_PIN, BRG>(leds, NUM_LEDS);
  FastLED.setBrightness(ctl.brightness);
  clearFrame();
  FastLED.show();

  initState();
  modeStart = millis();
  Serial.println();
  Serial.println("ESP32 Lisbon J1 RED ORGANIC STROBE BLEND LIVE test");
  Serial.println("Full brightness red-only; FastLED color order BRG.");
  Serial.println("GPIO25 -> AHCT125 pin3 -> J1 DATA. Fade pools + strobes + slower chases together.");
  Serial.println("Live serial commands: b/d/s/c/f 0..255, m 0..3 or 255 auto, x blackout, r reseed, ? status");
  printControls();
}

void loop() {
  ++frameCounter;
  handleSerialControls();
  maybeAdvanceMode();
  organicMixedIntensity();
  FastLED.show();

  // Status LED flickers as a local heartbeat; not synced exactly to strip.
  digitalWrite(STATUS_LED_PIN, (frameCounter & 0x07) < 2 ? HIGH : LOW);

  uint8_t liveDelayMax = FRAME_DELAY_MAX_MS + ((uint16_t)(255 - ctl.chase) * 8 / 255);
  delay(FRAME_DELAY_MIN_MS + randN(liveDelayMax - FRAME_DELAY_MIN_MS + 1));
}
