// Definitions for the faithful M5Unified shim (see include/M5Unified.h).
// Only this TU pulls in SDL — everywhere else gets it transitively through
// M5GFX or not at all.

#include <M5Unified.h>
#include <SDL2/SDL.h>
#include <stdlib.h>

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
  BtnA._set(a);
  BtnB._set(b);
  BtnPWR._set(p);
}
