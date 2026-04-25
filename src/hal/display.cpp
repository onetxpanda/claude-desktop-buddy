#include "display.h"
#include <M5Unified.h>

static M5Canvas _spr(&M5.Display);

namespace hal { namespace display {

void begin() {
  M5.Display.setColorDepth(16);
  // PSRAM-backed sprites have DMA cache coherency issues with M5GFX's pushSprite
  // on Core2 — sprite writes don't get flushed before DMA reads. Force internal
  // RAM. At 16bpp a 320x240 sprite is 150 KB which won't fit in internal RAM
  // alongside BLE, so drop to 8bpp on PSRAM-equipped boards. StickC has no PSRAM
  // and a 135x240 sprite at 16bpp (65 KB) fits internal RAM trivially.
  if (psramFound()) {
    _spr.setColorDepth(8);
    _spr.setPsram(false);
  }
  _spr.createSprite(M5.Display.width(), M5.Display.height());
  if (psramFound()) {
    _spr.createPalette();   // 8bpp paletted sprites need an explicit palette
  }
}

M5GFX&       lcd()           { return M5.Display; }
M5Canvas&    sprite()        { return _spr; }
int  width()                 { return M5.Display.width(); }
int  height()                { return M5.Display.height(); }
void setRotation(uint8_t r)  { M5.Display.setRotation(r); }
void push()                  { _spr.pushSprite(&M5.Display, 0, 0); }

}}
