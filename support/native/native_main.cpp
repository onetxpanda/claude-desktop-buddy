// Native entrypoint: drives the firmware's setup()/loop() the same way the
// Arduino runtime would on-device, plus a screenshot capture mechanism for
// headless CI. Configurable via env vars so the same binary works for
// interactive demos and for CI/regression tests.
//
//   SCREENSHOT_FILE=out.ppm     Where to write the screenshot (PPM, P6).
//   SCREENSHOT_AT_MS=2000       When (after setup() completes) to capture.
//   SCREENSHOTS_EVERY_MS=500    Capture every N ms, suffixed _0001.ppm etc.
//   EXIT_AFTER_MS=4000          Exit cleanly after this much wall time.
//
// Convert PPM → PNG with `convert out.ppm out.png` (ImageMagick).
//
// On native, M5GFX's SDL backend opens a window during display::begin().
// Headless usage requires Xvfb: `xvfb-run -a -s "-screen 0 1280x720x24" pio run -e emulator_stickc -t exec`.

#include <stdio.h>
#include <stdlib.h>
#include <stdint.h>
#include <string.h>

#include <Arduino.h>
#include <LittleFS.h>
#include <M5GFX.h>
#include "hal/display.h"

// Globals declared as `extern` in the shim headers; defined here so there's
// exactly one TU holding them.
HardwareSerial   Serial;
_ESPClass        ESP;
_LittleFSClass   LittleFS;

// The firmware's entrypoints — declared in main.cpp.
extern void setup();
extern void loop();

namespace {

// PPM (P6) is the simplest portable RGB format with no external dependencies.
// Width/height come from the live LCD — Core2 emits 320×240, StickC 135×240.
bool save_ppm(const char* path) {
  M5GFX& g = hal::display::lcd();
  int w = g.width(), h = g.height();
  FILE* f = fopen(path, "wb");
  if (!f) return false;
  fprintf(f, "P6\n%d %d\n255\n", w, h);
  for (int y = 0; y < h; y++) {
    for (int x = 0; x < w; x++) {
      uint32_t c = g.readPixel(x, y);   // returns 0xRRGGBB on lgfx
      uint8_t rgb[3] = {
        (uint8_t)((c >> 16) & 0xFF),
        (uint8_t)((c >>  8) & 0xFF),
        (uint8_t)( c        & 0xFF),
      };
      fwrite(rgb, 1, 3, f);
    }
  }
  fclose(f);
  return true;
}

uint32_t parse_u32_env(const char* k, uint32_t fallback = 0) {
  const char* v = getenv(k);
  return v ? (uint32_t)strtoul(v, nullptr, 10) : fallback;
}

}  // anon

int main(int /*argc*/, char** /*argv*/) {
  setup();

  uint32_t shotAt          = parse_u32_env("SCREENSHOT_AT_MS", 0);
  uint32_t shotsEvery      = parse_u32_env("SCREENSHOTS_EVERY_MS", 0);
  uint32_t exitAfter       = parse_u32_env("EXIT_AFTER_MS", 0);
  const char* shotPath     = getenv("SCREENSHOT_FILE");

  bool shotTaken = false;
  uint32_t nextShotAt = shotsEvery;
  uint32_t shotIdx = 0;

  // millis() origin in Arduino.h is the first call site; lock it now so
  // millis()==0 reliably happens before/around setup() rather than mid-tick.
  extern uint32_t millis();
  uint32_t t0 = millis();
  (void)t0;

  while (true) {
    loop();
    uint32_t t = millis();

    if (!shotTaken && shotAt && shotPath && t >= shotAt) {
      if (save_ppm(shotPath)) {
        fprintf(stderr, "[emu] screenshot → %s @ %ums\n", shotPath, t);
      } else {
        fprintf(stderr, "[emu] screenshot failed: %s\n", shotPath);
      }
      shotTaken = true;
    }

    if (shotsEvery && shotPath && t >= nextShotAt) {
      char path[512];
      // Insert a numeric suffix before the extension (or at end if no dot).
      const char* dot = strrchr(shotPath, '.');
      if (dot) {
        int prefixLen = (int)(dot - shotPath);
        snprintf(path, sizeof(path), "%.*s_%04u%s", prefixLen, shotPath, (unsigned)shotIdx++, dot);
      } else {
        snprintf(path, sizeof(path), "%s_%04u", shotPath, (unsigned)shotIdx++);
      }
      save_ppm(path);
      nextShotAt += shotsEvery;
    }

    if (exitAfter && t >= exitAfter) {
      fprintf(stderr, "[emu] exit after %ums\n", t);
      break;
    }
  }
  return 0;
}
