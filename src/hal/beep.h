#pragma once
#include <stdint.h>

namespace hal { namespace beep {
  void begin();
  void tick();
  void tone(uint16_t freq, uint16_t ms); // raw — caller gates on settings
}}
