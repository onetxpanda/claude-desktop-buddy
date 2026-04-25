#pragma once
#include <M5Unified.h>

namespace hal { namespace display {
  void begin();
  M5GFX&       lcd();
  M5Canvas&    sprite();
  int  width();
  int  height();
  void setRotation(uint8_t r);
  void push();                     // sprite → LCD
  bool isLarge();                  // true when display width ≥ 320 (Core2-class)
}}
