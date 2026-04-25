#pragma once
#include <stdint.h>

namespace screen { namespace settings {
  void    draw();
  uint8_t selected();
  void    setSelected(uint8_t i);
  uint8_t itemCount();
}}
