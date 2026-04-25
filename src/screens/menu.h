#pragma once
#include <stdint.h>
#include "../input.h"

namespace screen { namespace menu {
  void    draw();
  uint8_t selected();
  void    setSelected(uint8_t i);
  uint8_t itemCount();
  bool    handleButton(Btn b, BtnEvent e);
}}
