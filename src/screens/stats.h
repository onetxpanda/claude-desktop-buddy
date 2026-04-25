#pragma once
#include <stdint.h>
#include "../input.h"

namespace screen { namespace petstats {
  void    draw();
  void    nextPage();             // called when user presses B on the stats screen
  bool    handleButton(Btn b, BtnEvent e);
}}
