#include "display.h"
#include <M5Unified.h>

static M5Canvas _spr(&M5.Display);

namespace hal { namespace display {

void begin() {
  M5.Display.setColorDepth(16);
  if (psramFound()) {
    // Core2: 8bpp RGB332 in internal RAM. PSRAM-backed 16bpp sprites have DMA
    // cache coherency issues with M5GFX's pushSprite on this board, and a
    // 16bpp full-screen sprite (150 KB) doesn't fit alongside BLE in internal
    // RAM. 8bpp at 320×240 = 76 KB fits comfortably. Skipping createPalette()
    // keeps the canvas in RGB332 mode (R3-G3-B2 packed in 8 bits) so drawing
    // with raw 16bpp colors quantizes directly to RGB332 — colorful and cheap,
    // versus paletted mode which would require explicit index-based drawing.
    _spr.setColorDepth(8);
    _spr.setPsram(false);
  } else {
    _spr.setColorDepth(16);
  }
  _spr.createSprite(M5.Display.width(), M5.Display.height());
}

M5GFX&       lcd()           { return M5.Display; }
M5Canvas&    sprite()        { return _spr; }
int  width()                 { return M5.Display.width(); }
int  height()                { return M5.Display.height(); }
void setRotation(uint8_t r)  { M5.Display.setRotation(r); }
void push()                  { _spr.pushSprite(&M5.Display, 0, 0); }
bool isLarge()               { return M5.Display.width() >= 320; }

}}
