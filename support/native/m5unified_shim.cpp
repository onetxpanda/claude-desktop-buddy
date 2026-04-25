// Definitions for the faithful M5Unified shim (see include/M5Unified.h).
// Only this TU pulls in SDL — everywhere else gets it transitively through
// M5GFX or not at all.

#include <M5Unified.h>
#include <SDL2/SDL.h>
#include <stdlib.h>
#include <string.h>
#include <stdio.h>

// Scripted input — lets a CI run drive button state without a real keyboard.
// Format: EMULATOR_INPUT="A:500-1300,B:1500-1550,P:2000-2050"
//   Each entry: BTN(A|B|P):start_ms-end_ms. Buttons are forced "down" while
//   their window is active, layered on top of any real SDL keyboard input.
struct ScriptEntry { uint32_t at_ms; uint32_t until_ms; char btn; };
static ScriptEntry _script[32];
static int _scriptN = 0;
static bool _scriptLoaded = false;

static void _loadScript() {
  if (_scriptLoaded) return;
  _scriptLoaded = true;
  const char* s = getenv("EMULATOR_INPUT");
  if (!s || !*s) return;
  while (*s && _scriptN < 32) {
    while (*s == ' ' || *s == ',') s++;
    if (!*s) break;
    char btn = *s++;
    if (*s != ':') break;
    s++;
    char* end = nullptr;
    uint32_t a = (uint32_t)strtoul(s, &end, 10);
    if (!end || *end != '-') break;
    s = end + 1;
    uint32_t b = (uint32_t)strtoul(s, &end, 10);
    if (!end) break;
    s = end;
    _script[_scriptN++] = { a, b, btn };
  }
  fprintf(stderr, "[emu] loaded %d input script entries\n", _scriptN);
}

M5_Class M5;

void M5_Class::begin() {
  Display.init();
#if defined(NATIVE_TARGET_CORE2)
  Display.setRotation(1);   // Core2 ships landscape by default
#else
  Display.setRotation(0);   // StickC ships portrait
#endif
  Display.fillScreen(0x0000);
}

void M5_Class::update() {
  // Drain SDL events so the M5GFX SDL window stays responsive and so
  // SDL_GetKeyboardState reflects current input. Window-close kills the
  // process — same effective behavior as the AXP long-press on hardware.
  SDL_Event ev;
  while (SDL_PollEvent(&ev)) {
    if (ev.type == SDL_QUIT) _Exit(0);
  }
  const Uint8* keys = SDL_GetKeyboardState(nullptr);
  bool a = keys && (keys[SDL_SCANCODE_A] || keys[SDL_SCANCODE_LEFT]);
  bool b = keys && (keys[SDL_SCANCODE_B] || keys[SDL_SCANCODE_RIGHT]);
  bool p = keys && keys[SDL_SCANCODE_P];

  _loadScript();
  uint32_t now = millis();
  for (int i = 0; i < _scriptN; i++) {
    if (now >= _script[i].at_ms && now < _script[i].until_ms) {
      if (_script[i].btn == 'A') a = true;
      if (_script[i].btn == 'B') b = true;
      if (_script[i].btn == 'P') p = true;
    }
  }

  BtnA._set(a);
  BtnB._set(b);
  BtnPWR._set(p);
}
