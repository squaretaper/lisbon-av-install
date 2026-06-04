#include <Arduino.h>
#include <FastLED.h>

// Lisbon AV dual-strip pattern test.
// Wiring pattern from audited build:
//   J1 DATA: ESP32 GPIO25 -> AHCT125 U1 pin 2/3 -> R1 470R -> J1 DATA
//   J2 DATA: ESP32 GPIO26 -> AHCT125 U1 pin 5/6 -> R2 470R -> J2 DATA
//   Color order proven on J1 bench test: BRG
//   Status LED: GPIO27 -> R3 220R -> LED -> GND
//   Case light-pipe LEDs: bottom->top GPIO13, GPIO14, GPIO32, GPIO33
//
// HARDWARE NOTE — AHCT125 mortality:
//   Do NOT hot-plug J1/J2 strip cables. WS2811 DI clamp diodes back-inject
//   into the buffer output and kill U1. Power down the 12V strip rail first.
//   2026-05-31: lost one U1 hot-plugging the J2 universe (Joshua). Replaced.
//   Future board rev: add TVS (SMAJ5.0A) + Schottky (BAT54) on each buffer
//   output for hot-plug tolerance.

static constexpr uint8_t J1_DATA_PIN = 25;
static constexpr uint8_t J2_DATA_PIN = 26;
static constexpr uint8_t STATUS_LED_PIN = 27;
static constexpr uint8_t LIGHT_PIPE_PINS[] = {13, 14, 32, 33};

// BTF WS2811 12V 30 LED/m x 5m is typically 3 physical LEDs per addressable IC:
// Each universe: 3 chained strips x 2m x 30 px/m, nominal 180 physical = 60
// logical WS2811 pixels. In practice each 2m strip ships with 21 ICs (one
// extra at the end), so the chain is 63 logical, not 60. Tail goes dark if
// this is undercounted: 3 logical pixels per strip = 9 physical LEDs.
// Hardware count wins over arithmetic. Verified with Joshua 2026-06-03.
static constexpr uint16_t NUM_LEDS = 63;

// Bench-safe default. Pure red only: no amber/white accents in the installed strips.
static uint8_t gBrightness = 64;  // 25% of FastLED max; not full-bright.
static uint8_t gChaseStepMs = 96;  // Lower = faster drone chase, adjusted live over serial.
static uint8_t gPulseDepth = 42;   // Background red pulse depth for drone chase.
static uint8_t gPacketSpan = 20;   // Frequency-linked phase offset between crossing packets.
static constexpr uint8_t FRAME_MS = 28;
static constexpr uint32_t AUTO_MODE_MS = 9000;

CRGB stripJ1[NUM_LEDS];
CRGB stripJ2[NUM_LEDS];

enum Mode : uint8_t {
  MODE_ALL_RED = 0,
  MODE_CHASE = 1,
  MODE_GLITCH = 2,
  MODE_RUNNING_TOGETHER = 3,
  MODE_DYSTOPIAN = 4,
  MODE_BLACKOUT = 5,
};

static Mode mode = MODE_ALL_RED;
static bool autoMode = true;
static uint32_t modeStartedAt = 0;
static uint32_t lastFrameAt = 0;
static uint32_t lastStatusAt = 0;
static uint32_t frameNo = 0;

const char* modeName(Mode m) {
  switch (m) {
    case MODE_ALL_RED: return "ALL RED";
    case MODE_CHASE: return "CHASING RED TRAINS";
    case MODE_GLITCH: return "GLITCH STROBE / FAULT SPARKS";
    case MODE_RUNNING_TOGETHER: return "RUNNING TOGETHER";
    case MODE_DYSTOPIAN: return "DYSTOPIAN BREATH + SCAN";
    case MODE_BLACKOUT: return "BLACKOUT";
  }
  return "UNKNOWN";
}

void printMode() {
  Serial.print("MODE: ");
  Serial.print(modeName(mode));
  Serial.print(" | brightness=");
  Serial.print(gBrightness);
  Serial.print(" | chase_ms=");
  Serial.print(gChaseStepMs);
  Serial.print(" | pulse=");
  Serial.print(gPulseDepth);
  Serial.print(" | span=");
  Serial.print(gPacketSpan);
  Serial.print(" | auto=");
  Serial.println(autoMode ? "on" : "off");
}

void setMode(Mode m, bool keepAuto = false) {
  mode = m;
  modeStartedAt = millis();
  if (!keepAuto) autoMode = false;
  FastLED.clear(true);
  printMode();
}

void blackout() {
  fill_solid(stripJ1, NUM_LEDS, CRGB::Black);
  fill_solid(stripJ2, NUM_LEDS, CRGB::Black);
}

void initLightPipes() {
  for (uint8_t p : LIGHT_PIPE_PINS) {
    pinMode(p, OUTPUT);
    digitalWrite(p, LOW);
  }
}

void setLightPipes(uint8_t mask) {
  for (uint8_t i = 0; i < 4; ++i) {
    digitalWrite(LIGHT_PIPE_PINS[i], (mask & (1 << i)) ? HIGH : LOW);
  }
}

void renderLightPipes(uint32_t t) {
  switch (mode) {
    case MODE_ALL_RED:
      // Solid case indicators during the unambiguous red/channel test.
      setLightPipes(0b1111);
      break;
    case MODE_CHASE:
      // Bottom-to-top chase, matching the physical light-pipe order.
      setLightPipes(1 << ((t / 140) % 4));
      break;
    case MODE_GLITCH:
      // High-frequency audio faults: short pure-red strobe gates plus sparse fault flicker.
      if ((t % 130) < 34) {
        setLightPipes(0b1111);
      } else {
        setLightPipes(random8() < 70 ? (1 << random8(4)) : 0);
      }
      break;
    case MODE_RUNNING_TOGETHER:
      // Two-pixel marching pair for a synchronized-machine feel.
      {
        uint8_t step = (t / 180) % 4;
        setLightPipes((1 << step) | (1 << ((step + 1) % 4)));
      }
      break;
    case MODE_DYSTOPIAN:
      // Slow patrol with occasional institutional blackout.
      if ((t % 5300) < 70 || (t % 7900) < 45) {
        setLightPipes(0);
      } else {
        setLightPipes(1 << ((t / 360) % 4));
      }
      break;
    case MODE_BLACKOUT:
      setLightPipes(0);
      break;
  }
}

void statusHeartbeat() {
  const uint32_t now = millis();
  if (now - lastStatusAt >= 500) {
    lastStatusAt = now;
    digitalWrite(STATUS_LED_PIN, !digitalRead(STATUS_LED_PIN));
  }
}

void allRedPattern(uint32_t t) {
  // Dark, solid, unambiguous channel/color test. Slight breathing keeps it obviously alive.
  uint8_t breathe = sin8(t / 18);          // 0..255
  uint8_t red = 130 + scale8(breathe, 85); // 130..215 before global brightness
  fill_solid(stripJ1, NUM_LEDS, CRGB(red, 0, 0));
  fill_solid(stripJ2, NUM_LEDS, CRGB(red, 0, 0));
}

void addWrappedRed(CRGB* strip, int idx, uint8_t level) {
  idx %= NUM_LEDS;
  if (idx < 0) idx += NUM_LEDS;
  strip[idx] += CRGB(level, 0, 0);
}

void redPacket(CRGB* strip, int head, int direction, uint8_t peak) {
  // Short packets leave most pixels black, so the drone reads as small machines
  // chasing and crossing each other rather than one long circular loop.
  for (uint8_t k = 0; k < 4; ++k) {
    uint8_t level = qsub8(peak, k * 58);
    if (level > 0) addWrappedRed(strip, head - direction * k, level);
  }
}

uint16_t wrappedDistance(uint16_t a, uint16_t b) {
  uint16_t direct = a > b ? a - b : b - a;
  return min<uint16_t>(direct, NUM_LEDS - direct);
}

void chasePattern(uint32_t t) {
  // Mostly black canvas: the low-frequency drone should be present as motion,
  // not as every LED being permanently lit. BUT on low drones (wide span)
  // operator (6/4) wants ~2x packet density and more "broken" texture —
  // random sparks + extra phantom packets that flicker in and out.
  fill_solid(stripJ1, NUM_LEDS, CRGB::Black);
  fill_solid(stripJ2, NUM_LEDS, CRGB::Black);

  uint8_t stepMs = gChaseStepMs;
  if (stepMs < 18) stepMs = 18;
  if (stepMs > 168) stepMs = 168;
  uint8_t span = gPacketSpan;
  if (span < 8) span = 8;
  if (span > 44) span = 44;
  uint8_t halfSpan = span / 2;
  if (halfSpan < 4) halfSpan = 4;

  // Density mode: low drones (wide span = lots of cross-rhythm) get the
  // extra-packet layer + scatter sparks. Higher drones (tight span) stay
  // sparse to keep the original "machines chasing" feel.
  bool denseDrone = span >= 24;

  // The Mac maps the actual drone frequency into stepMs and span. Low drones
  // move more slowly and use wider cross-rhythm offsets; higher drones tighten
  // into smaller, quicker packets.
  uint32_t phaseA = t / stepMs;
  uint32_t phaseB = t / (stepMs + 9 + span / 3);
  uint32_t phaseC = t / (stepMs + 17 + span / 2);
  uint32_t phaseD = t / (stepMs + 5 + halfSpan);     // new: 4th cross-phase for density
  uint16_t p1 = phaseA % NUM_LEDS;
  uint16_t p2 = (NUM_LEDS + span - 1 - (phaseB % NUM_LEDS)) % NUM_LEDS;
  uint16_t p3 = (phaseA / 2 + halfSpan) % NUM_LEDS;
  uint16_t p4 = (NUM_LEDS + NUM_LEDS / 2 + span / 3 - (phaseC % NUM_LEDS)) % NUM_LEDS;
  uint16_t p5 = (phaseD + NUM_LEDS / 3) % NUM_LEDS;
  uint16_t p6 = (NUM_LEDS + NUM_LEDS / 4 - (phaseD * 2 % NUM_LEDS)) % NUM_LEDS;
  uint16_t p7 = (phaseB + phaseC + halfSpan) % NUM_LEDS;
  uint16_t p8 = (NUM_LEDS + NUM_LEDS * 2 / 3 - (phaseA + phaseC) % NUM_LEDS) % NUM_LEDS;

  uint8_t pulsePeriod = 11 + stepMs / 12;
  uint8_t ghostPeriod = 17 + span / 2;
  uint8_t subPeriod = 23 + stepMs / 10 + span / 3;
  uint8_t pulse = sin8(t / pulsePeriod);
  uint8_t ghostPulse = sin8(t / ghostPeriod + 85);
  uint8_t subPulse = sin8(t / subPeriod + 171);
  uint8_t peak = qadd8(84, scale8(pulse, gPulseDepth));
  uint8_t ghost = qadd8(28, scale8(ghostPulse, gPulseDepth / 2));
  uint8_t satellite = qadd8(18, scale8(subPulse, max<uint8_t>(8, gPulseDepth / 3)));

  redPacket(stripJ1, p1, 1, peak);
  redPacket(stripJ1, p2, -1, qadd8(60, scale8(ghostPulse, gPulseDepth)));
  redPacket(stripJ2, NUM_LEDS - 1 - p1, -1, peak);
  redPacket(stripJ2, p3, 1, ghost);
  redPacket(stripJ2, p4, -1, ghost);

  if (span >= 22) {
    // Wider low-frequency spans get slower satellites that cross the main packets,
    // giving the drone movement more machinery without filling the strip.
    redPacket(stripJ1, p3 + span / 3, 1, satellite);
    redPacket(stripJ1, p4 - span / 4, -1, satellite);
    redPacket(stripJ2, p2 + halfSpan, -1, satellite);
  }

  if (denseDrone) {
    // Extra packet density layer for low drones. These packets phase-shift
    // against the primaries so the strip reads as ~2x as lit without
    // becoming a steady wash. Brightness is intentionally between peak and
    // satellite so they don't dominate the primary motion. The extra
    // crossings between primary and dense packets are what give the
    // "more broken" feel — multiple chains weaving against each other,
    // NOT random per-frame flicker.
    //
    // 6/4 round 2: REMOVED the per-frame random sparks (8-14 random LEDs
    // every tick) and the periodic random-burst breakthrough. Both were
    // reading as strobe-baked-into-chase because they fire at frame rate
    // independent of any input — pure visual noise. Operator: "low freqs
    // = running lights with some broken and pulsing chains. glitch =
    // strobe." Sparks were strobe pretending to be chase.
    uint8_t denseLevel = qadd8(48, scale8(pulse, gPulseDepth * 3 / 4));
    uint8_t denseGhost = qadd8(36, scale8(subPulse, gPulseDepth / 2));
    redPacket(stripJ1, p5, 1, denseLevel);
    redPacket(stripJ1, p6, -1, denseGhost);
    redPacket(stripJ1, p7, 1, denseGhost);
    redPacket(stripJ2, p5, -1, denseLevel);
    redPacket(stripJ2, p7, 1, denseGhost);
    redPacket(stripJ2, p8, -1, denseLevel);
  }

  uint8_t collisionWindow = 3 + span / 14;
  uint16_t collisionA = wrappedDistance(p1, p2);
  uint16_t collisionB = wrappedDistance((uint16_t)((NUM_LEDS - 1 - p1) % NUM_LEDS), p3);
  uint32_t collisionPeriod = 1180 + static_cast<uint32_t>(span) * 38;
  if (collisionA <= collisionWindow || collisionB <= collisionWindow || (t % collisionPeriod) < (64 + span)) {
    uint8_t hit = qadd8(142, scale8(pulse, 92));
    uint16_t c1 = (uint16_t)(p1 + p2) / 2;
    uint16_t c2 = (uint16_t)((NUM_LEDS - 1 - p1) + p3) / 2;
    for (int8_t k = -1; k <= 1; ++k) {
      addWrappedRed(stripJ1, c1 + k, hit);
      addWrappedRed(stripJ2, c2 + k, hit);
    }
  }

  // Tiny black holes make the pattern breathe without killing the base motion.
  uint32_t blackoutPeriod = 1840 + static_cast<uint32_t>(span) * 43;
  if ((t % blackoutPeriod) < (42 + span / 3)) {
    for (uint8_t k = 0; k < 7; ++k) {
      stripJ1[(p1 + k * span) % NUM_LEDS] = CRGB::Black;
      stripJ2[(p2 + k * (halfSpan + 3)) % NUM_LEDS] = CRGB::Black;
    }
  }
}

void glitchPattern(uint32_t t) {
  // High-frequency audio glitches: brutal pure-red flashes against actual black.
  // Realtime-reactive (6/4 round 2): the OLD design held strobe ON for the
  // first 420ms after mode entry so a single trigger always produced a
  // noticeable burst. But the sync now drops back to mode 1 the next status
  // tick (~20ms) when CV7 falls, which left the strip strobing for 400ms
  // of "ghost" after CV7 was already gone. Operator wants frame-accurate:
  // strobe duration = CV7 duration. Removed the 420ms hold; the periodic
  // gate alone provides the visible hard-strobe rhythm while the mode is
  // active.
  bool blackGate = ((t - modeStartedAt) % 124) >= 42 && ((t - modeStartedAt) % 124) < 76;
  if (blackGate) {
    blackout();
    return;
  }

  bool strobeGate = (t % 72) < 34 || ((t + 57) % 190) < 28;
  if (strobeGate) {
    fill_solid(stripJ1, NUM_LEDS, CRGB(255, 0, 0));
    fill_solid(stripJ2, NUM_LEDS, CRGB(255, 0, 0));
    return;
  }

  blackout();

  uint8_t events = random8(4, 13);
  for (uint8_t e = 0; e < events; ++e) {
    CRGB* s = random8() & 1 ? stripJ1 : stripJ2;
    uint16_t p = random16(NUM_LEDS);
    uint8_t red = random8(140, 255);
    s[p] = CRGB(red, 0, 0);
    if (p + 1 < NUM_LEDS && random8() < 120) s[p + 1] = CRGB(red / 2, 0, 0);
    if (p > 0 && random8() < 80) s[p - 1] = CRGB(red / 3, 0, 0);
  }

  if ((t / 90) % 11 == 0) {
    blackout(); // hard dropout reads as glitch, and is current-safe.
  }
}

void runningTogetherPattern(uint32_t t) {
  // Both strips run in sync: the two sides feel like one machine breathing together.
  fadeToBlackBy(stripJ1, NUM_LEDS, 72);
  fadeToBlackBy(stripJ2, NUM_LEDS, 72);
  int pos = (t / 38) % NUM_LEDS;

  for (uint8_t k = 0; k < 10; ++k) {
    int idx = (pos + k) % NUM_LEDS;
    uint8_t level = 255 - k * 22;
    CRGB c(level, 0, 0);
    stripJ1[idx] += c;
    stripJ2[idx] += c;
  }

  // Occasional synchronized marker pulse at opposite end.
  if ((t / 700) % 4 == 0) {
    int marker = (NUM_LEDS - 1 - pos + NUM_LEDS) % NUM_LEDS;
    stripJ1[marker] += CRGB(80, 0, 0);
    stripJ2[marker] += CRGB(80, 0, 0);
  }
}

void dystopianPattern(uint32_t t) {
  // Low red ambience, patrol scanlines, ember noise, occasional institutional blackout.
  uint8_t base = 8 + scale8(sin8(t / 42), 32);
  fill_solid(stripJ1, NUM_LEDS, CRGB(base, 0, 0));
  fill_solid(stripJ2, NUM_LEDS, CRGB(base, 0, 0));

  int scan = (t / 55) % NUM_LEDS;
  int scan2 = (scan + NUM_LEDS / 2) % NUM_LEDS;
  for (uint8_t k = 0; k < 5; ++k) {
    uint8_t level = 180 - k * 32;
    stripJ1[(scan + k) % NUM_LEDS] += CRGB(level, 0, 0);
    stripJ2[(scan2 + k) % NUM_LEDS] += CRGB(level, 0, 0);
  }

  if (random8() < 28) {
    CRGB ember(random8(35, 120), 0, 0);
    stripJ1[random16(NUM_LEDS)] += ember;
    stripJ2[random16(NUM_LEDS)] += ember;
  }

  // Frame-synced blackout cuts, short and sparse.
  if ((t % 5300) < 70 || (t % 7900) < 45) {
    blackout();
  }
}

void renderFrame() {
  const uint32_t t = millis();

  if (autoMode && t - modeStartedAt > AUTO_MODE_MS) {
    mode = static_cast<Mode>((static_cast<uint8_t>(mode) + 1) % 5);
    modeStartedAt = t;
    FastLED.clear(true);
    printMode();
  }

  switch (mode) {
    case MODE_ALL_RED: allRedPattern(t); break;
    case MODE_CHASE: chasePattern(t); break;
    case MODE_GLITCH: glitchPattern(t); break;
    case MODE_RUNNING_TOGETHER: runningTogetherPattern(t); break;
    case MODE_DYSTOPIAN: dystopianPattern(t); break;
    case MODE_BLACKOUT: blackout(); break;
  }

  renderLightPipes(t);

  FastLED.setBrightness(gBrightness);
  FastLED.show();
  frameNo++;
}

void printHelp() {
  Serial.println("Commands: a=auto, 0=all red, 1=chase, 2=glitch, 3=running together, 4=dystopian, x=blackout, +=brighter, -=dimmer, >=faster chase, <=slower chase, ]=deeper pulse, [=shallower pulse, }=wider packet span, {=tighter packet span, ?=status");
}

void handleSerial() {
  while (Serial.available() > 0) {
    char c = Serial.read();
    switch (c) {
      case 'a': case 'A':
        autoMode = true;
        mode = MODE_ALL_RED;
        modeStartedAt = millis();
        FastLED.clear(true);
        printMode();
        break;
      case '0': setMode(MODE_ALL_RED); break;
      case '1': setMode(MODE_CHASE); break;
      case '2': setMode(MODE_GLITCH); break;
      case '3': setMode(MODE_RUNNING_TOGETHER); break;
      case '4': setMode(MODE_DYSTOPIAN); break;
      case 'x': case 'X': setMode(MODE_BLACKOUT); break;
      case '+':
        gBrightness = qadd8(gBrightness, 16);
        printMode();
        break;
      case '-':
        gBrightness = qsub8(gBrightness, 16);
        printMode();
        break;
      case '>':
        gChaseStepMs = (gChaseStepMs > 22) ? (gChaseStepMs - 4) : 18;
        printMode();
        break;
      case '<':
        gChaseStepMs = (gChaseStepMs < 164) ? (gChaseStepMs + 4) : 168;
        printMode();
        break;
      case ']':
        gPulseDepth = (gPulseDepth < 104) ? (gPulseDepth + 8) : 112;
        printMode();
        break;
      case '[':
        gPulseDepth = (gPulseDepth > 16) ? (gPulseDepth - 8) : 8;
        printMode();
        break;
      case '}':
        gPacketSpan = (gPacketSpan < 42) ? (gPacketSpan + 2) : 44;
        printMode();
        break;
      case '{':
        gPacketSpan = (gPacketSpan > 10) ? (gPacketSpan - 2) : 8;
        printMode();
        break;
      case '?':
        printMode();
        printHelp();
        break;
      default:
        break;
    }
  }
}

void setup() {
  Serial.begin(115200);
  delay(300);

  pinMode(STATUS_LED_PIN, OUTPUT);
  digitalWrite(STATUS_LED_PIN, LOW);
  initLightPipes();

  FastLED.addLeds<WS2811, J1_DATA_PIN, BRG>(stripJ1, NUM_LEDS);
  FastLED.addLeds<WS2811, J2_DATA_PIN, BRG>(stripJ2, NUM_LEDS);
  FastLED.setBrightness(gBrightness);
  FastLED.clear(true);

  random16_add_entropy(analogRead(36));
  modeStartedAt = millis();

  Serial.println();
  Serial.println("Lisbon AV dual WS2811 strip pattern test");
  Serial.println("J1: GPIO25 -> AHCT125 -> R1 470R -> J1 DATA");
  Serial.println("J2: GPIO26 -> AHCT125 -> R2 470R -> J2 DATA");
  Serial.println("Color order: BRG. Logical pixels: 50. Brightness starts at 64/255.");
  Serial.println("Auto cycle: all red, chase, glitch, running together, dystopian.");
  Serial.println("Case light pipes active on GPIO13/14/32/33 bottom-to-top.");
  printHelp();
  printMode();
}

void loop() {
  handleSerial();
  statusHeartbeat();
  uint32_t now = millis();
  if (now - lastFrameAt >= FRAME_MS) {
    lastFrameAt = now;
    renderFrame();
  }
}
