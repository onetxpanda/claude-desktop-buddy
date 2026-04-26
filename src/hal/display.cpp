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

#if !defined(NATIVE_BUILD)
// ROM symbol — present on every ESP32 chip variant, no IDF version
// dependency. Same declaration M5GFX uses in Panel_FrameBufferBase.cpp:32
// and Panel_EPD.cpp:49 for exactly this scenario.
extern "C" int Cache_WriteBack_Addr(uint32_t addr, uint32_t size);
#endif

// PSRAM + DMA cache coherency: heap_caps_malloc(..., MALLOC_CAP_SPIRAM)
// returns a PSRAM address. CPU writes pixels through the D-cache; DMA
// reads PSRAM directly, bypassing cache, so it streams stale bytes to
// the LCD → white/green line garbage. Flush the dirty cache lines back
// to PSRAM before the push and DMA sees the latest pixels.
//
// M5GFX would do this for us if heap_capable_dma() reported PSRAM as
// non-DMA-capable, but esp_ptr_dma_capable() returns true for PSRAM on
// ESP32 classic (the chip's MMU IS technically DMA-capable from PSRAM,
// the coherency hole is a separate problem). Same path M5GFX uses for
// its FrameBuffer-backed panels — 32-byte aligned address & size,
// guaranteed by heap_caps_malloc with MALLOC_CAP_SPIRAM.
void push() {
#if !defined(NATIVE_BUILD)
  if (psramFound()) {
    Cache_WriteBack_Addr((uint32_t)_spr.getBuffer(),
                         (uint32_t)(_spr.width() * _spr.height() * sizeof(uint16_t)));
  }
#endif
  _spr.pushSprite(&M5.Display, 0, 0);
}

bool isLarge()               { return M5.Display.width() >= 320; }

}}
