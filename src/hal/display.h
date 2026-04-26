#pragma once
#include <M5Unified.h>

namespace hal { namespace display {
  void begin();
  M5GFX&  lcd();
  // sprite() now returns M5.Display directly — there's no off-screen
  // sprite buffer anymore. The PSRAM/DMA cache-coherency hole that
  // PSRAM-backed sprites trip on ESP32 classic was a sinkhole of partial
  // fixes (Cache_WriteBack_Addr isn't linkable on arduino-esp32 v2,
  // setPsram(false) forces 8bpp RGB332 quantization, scanline staging
  // didn't help on hardware). Direct draw to M5.Display sidesteps it
  // entirely: no PSRAM, no DMA-from-PSRAM, no quantization. ILI9342C's
  // GRAM scan-out at 60-70Hz is fast enough that direct SPI writes
  // don't tear in practice. push() is now a no-op kept for source
  // compatibility with the screens/ files.
  M5GFX&  sprite();
  int  width();
  int  height();
  void setRotation(uint8_t r);
  void push();
  bool isLarge();                  // true when display width ≥ 320 (Core2-class)
}}
