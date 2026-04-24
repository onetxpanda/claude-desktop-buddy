#pragma once
#include <M5StickCPlus.h>

namespace hal { namespace display {
  void begin();                    // no-op in A.1; owns sprite from A.2.6
  TFT_eSPI&    lcd();              // direct LCD (landscape clock, passkey)
  TFT_eSprite& sprite();           // shared drawing surface
  int  width();                    // 135 on StickC Plus
  int  height();                   // 240
  void setRotation(uint8_t r);     // 0..3
  void push();                     // sprite → LCD (sprite.pushSprite(0, 0))
}}
