#include "display.h"
#include <M5Unified.h>

static M5Canvas _spr(&M5.Display);

namespace hal { namespace display {

void begin() {
  M5.Display.setColorDepth(16);
  _spr.setColorDepth(16);
  if (psramFound()) {
    // Core2: 16bpp full-color sprite (150 KB) lives in PSRAM. M5GFX's
    // SpriteBuffer detects the allocation source and skips DMA on the
    // pushSprite path for PSRAM-backed buffers (SpriteBuffer::use_dma()
    // returns false), falling back to CPU-driven SPI. That avoids the
    // PSRAM/DMA cache-coherency issue without manual cache management:
    // CPU writes pixels through D-cache, CPU reads them back through
    // D-cache — coherent. ~5 ms per push instead of ~1 ms for DMA, well
    // within a 16 ms frame budget.
    _spr.setPsram(true);
  }
  _spr.createSprite(M5.Display.width(), M5.Display.height());
}

M5GFX&       lcd()           { return M5.Display; }
M5Canvas&    sprite()        { return _spr; }
int  width()                 { return M5.Display.width(); }
int  height()                { return M5.Display.height(); }
void setRotation(uint8_t r)  { M5.Display.setRotation(r); }

// Bypass _spr.pushSprite() because it routes through SpriteBuffer::use_dma(),
// which is `_source == Dma || heap_capable_dma(_buffer)`. heap_capable_dma()
// calls esp_ptr_dma_capable() — and on ESP32 classic that returns *true* for
// PSRAM, since PSRAM is DMA-capable at the silicon level. But PSRAM+DMA has
// a cache-coherency hole: DMA reads PSRAM directly, bypassing the D-cache the
// CPU just wrote pixels through, so DMA sees stale lines → the famous
// white/green garbage. M5GFX's "DMA disable with use SPIRAM" comment isn't
// actually what the code does for ESP32. Calling pushImage directly with the
// raw buffer dispatches to the non-DMA push (pushImage's use_dma defaults to
// false), so pixels go out via CPU-driven SPI: same CPU just wrote them
// through cache, reads them back through cache — coherent.
void push() {
  M5.Display.pushImage(0, 0, _spr.width(), _spr.height(),
                       (const uint16_t*)_spr.getBuffer());
}

bool isLarge()               { return M5.Display.width() >= 320; }

}}
