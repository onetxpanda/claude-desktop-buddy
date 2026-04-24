#pragma once
#include <stdint.h>

namespace hal { namespace buttons {
  bool pressedA();
  bool pressedB();
  bool heldA(uint16_t ms);              // M5.BtnA.pressedFor(ms)
  bool powerButtonPressed();            // AXP side-button tap (GetBtnPress() == 0x02)
}}
