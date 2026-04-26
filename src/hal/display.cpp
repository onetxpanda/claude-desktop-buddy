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

// Push the PSRAM-backed sprite to the LCD without tripping the PSRAM/DMA
// cache-coherency hole on ESP32 classic.
//
// Background: heap_caps_malloc(..., MALLOC_CAP_SPIRAM) returns a PSRAM
// address. CPU draws into it through the D-cache. M5GFX's pushSprite ends
// up at Bus_SPI::writeBytes(use_dma=true) — DMA reads PSRAM directly,
// bypassing the cache the CPU just wrote into, so the DMA engine streams
// stale bytes to the panel and the user sees the white/green line
// garbage. Cache_WriteBack_Addr would patch this in one ROM call, but
// that symbol isn't exposed in arduino-esp32 v2 + ESP32 classic — M5GFX
// itself only defines the shim for IDF 5.x or ESP32-S3 in
// Panel_FrameBufferBase.cpp:25-49.
//
// Workaround that doesn't depend on the unavailable ROM symbol: stage
// each scanline through a 640-byte internal-RAM scratch buffer. CPU
// memcpy from PSRAM goes through the D-cache (coherent — picks up the
// freshly-written pixels), and the subsequent writePixelsDMA reads from
// internal RAM, which IS DMA-coherent. Cost: 240 SPI transactions per
// frame instead of 1, but the panel's internal address-window auto-
// increment keeps each transaction tight (just the pixel data, no
// per-row column commands).
void push() {
  const int w = _spr.width();
  const int h = _spr.height();
  // Internal-RAM scratch — sized to the larger of the two boards (Core2
  // 320). At sizeof(uint16_t)*320 = 640 B, trivially fits in DRAM.
  static uint16_t scanline[320];
  const uint16_t* src = (const uint16_t*)_spr.getBuffer();

  M5.Display.startWrite();
  M5.Display.setAddrWindow(0, 0, w, h);
  for (int y = 0; y < h; ++y) {
    // CPU read of PSRAM goes through D-cache → sees the latest pixels.
    // Then DMA reads scanline[] which is in DMA-coherent internal RAM.
    memcpy(scanline, src + (size_t)y * w, w * sizeof(uint16_t));
    M5.Display.writePixelsDMA(scanline, w);
  }
  M5.Display.endWrite();
}

bool isLarge()               { return M5.Display.width() >= 320; }

}}
