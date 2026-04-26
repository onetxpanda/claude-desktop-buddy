#include "display.h"
#include <M5Unified.h>

// M5Canvas's parent-constructor sets `_psram = true` (M5GFX.h:281), unlike
// the LGFX_Sprite default. On Core2 a PSRAM-backed sprite produces visual
// garbage when pushed via DMA — CPU writes go through cache, DMA reads
// stale PSRAM. Force internal DMA RAM with setPsram(false) before
// createSprite(). With NimBLE (vs Bluedroid) the 16bpp 150 KB framebuffer
// fits in internal RAM.
static M5Canvas _spr(&M5.Display);

namespace hal { namespace display {

void begin() {
  M5.Display.setColorDepth(16);
  _spr.setPsram(false);
  _spr.setColorDepth(16);
  _spr.createSprite(M5.Display.width(), M5.Display.height());
}

M5GFX&     lcd()             { return M5.Display; }
M5Canvas&  sprite()          { return _spr; }
int  width()                 { return M5.Display.width(); }
int  height()                { return M5.Display.height(); }
void setRotation(uint8_t r)  { M5.Display.setRotation(r); }
void push()                  { _spr.pushSprite(0, 0); }
bool isLarge()               { return M5.Display.width() >= 320; }

}}
