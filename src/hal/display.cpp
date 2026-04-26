#include "display.h"
#include <M5Unified.h>

namespace hal { namespace display {

// No off-screen sprite. Drawing functions in screens/, buddy.cpp, and
// character.cpp write directly to M5.Display via the `canvas` reference
// (M5GFX&), which goes through M5GFX's own SPI bus management — exactly
// the path the M5Stack examples and the M5Unified docs document for the
// ILI9342C panel.
void begin() {
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
