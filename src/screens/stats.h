#pragma once
#include <stdint.h>
#include "../input.h"

namespace screen { namespace petstats {
  void    draw();
  void    nextPage();             // called when user presses B on the stats screen
  uint8_t currentPage();          // 0..(PET_PAGES-1)
  bool    handleButton(Btn b, BtnEvent e);
}}
