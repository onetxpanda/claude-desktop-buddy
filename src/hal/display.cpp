#include "display.h"
#include <M5Unified.h>

namespace hal { namespace display {

// No off-screen sprite. Drawing functions in screens/, buddy.cpp, and
// character.cpp write directly to M5.Display via the `canvas` reference
// (M5GFX&), which goes through M5GFX's own SPI bus management — exactly
// the path the M5Stack examples and the M5Unified docs document for the
// ILI9342C panel.
void begin() {
  // Core2's ILI9342C ships with rgb_order=false in M5Unified's
  // Panel_M5StackCore2 config, which sends MAD_BGR in MADCTL — telling
  // the panel to interpret incoming pixel bytes as BGR. M5GFX's color
  // converter outputs RGB565, so on hardware we get an R↔B swap (the
  // light blue-green buddy reads as orange). Flipping rgb_order to true
  // emits MAD_RGB, matching the data the rest of the lib sends.
  // setRotation re-emits MADCTL so the change takes effect.
  auto* p = M5.Display.panel();
  auto cfg = p->config();
  if (!cfg.rgb_order) {
    cfg.rgb_order = true;
    p->config(cfg);
    M5.Display.setRotation(M5.Display.getRotation());
  }
}

M5GFX&  lcd()                { return M5.Display; }
M5GFX&  sprite()             { return M5.Display; }
int  width()                 { return M5.Display.width(); }
int  height()                { return M5.Display.height(); }
void setRotation(uint8_t r)  { M5.Display.setRotation(r); }
// No-op: there's no buffered sprite to push, every drawing call already
// went straight to the LCD. Keeping the symbol so the ~30 push() callsites
// in screens/ and main.cpp don't need to be touched.
void push()                  { }
bool isLarge()               { return M5.Display.width() >= 320; }

}}
