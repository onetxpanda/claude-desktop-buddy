#pragma once
#include <stdint.h>
#include "../hal/rtc.h"

namespace screen { namespace clock {
  // orient: 0 = portrait (sprite), 1 or 3 = landscape (direct to LCD)
  void draw(uint8_t orient,
            const hal::rtc::Time& t,
            const hal::rtc::Date& d);
}}
