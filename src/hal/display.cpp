#include "display.h"
#include <M5Unified.h>
#include <esp32/rom/cache.h>

// On Core2 the M5Canvas sits in PSRAM (M5GFX flips _psram=true in the
// parent-aware constructor). PSRAM is cached and the cache is write-back,
// so CPU draws land in cache lines while SPI DMA reads PSRAM directly —
// stale → white/green lines. Cache_Flush writes dirty lines back to
// PSRAM before each pushSprite. ESP32 has no per-address writeback
// (Cache_WriteBack_Addr is S2/S3 only), so we flush the whole cache
// for both cores. Cheap enough at UI framerates; expensive enough that
// we gate it on psramFound() to keep StickC's pure-internal-RAM path free.
static M5Canvas _spr(&M5.Display);

namespace hal { namespace display {

void begin() {
  M5.Display.setColorDepth(16);
  _spr.setColorDepth(16);
  _spr.createSprite(M5.Display.width(), M5.Display.height());
}

M5GFX&     lcd()             { return M5.Display; }
M5Canvas&  sprite()          { return _spr; }
int  width()                 { return M5.Display.width(); }
int  height()                { return M5.Display.height(); }
void setRotation(uint8_t r)  { M5.Display.setRotation(r); }
void push() {
  if (psramFound()) {
    Cache_Flush(0);
    Cache_Flush(1);
  }
  _spr.pushSprite(0, 0);
}
bool isLarge()               { return M5.Display.width() >= 320; }

}}
