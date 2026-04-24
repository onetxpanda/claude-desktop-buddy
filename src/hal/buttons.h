#pragma once
#include <stdint.h>

namespace hal { namespace buttons {
  bool pressedA();
  bool pressedB();
  bool heldA(uint16_t ms);              // M5.BtnA.pressedFor(ms)
  bool wasReleasedA();                  // M5.BtnA.wasReleased() — true once on edge
  bool wasPressedB();                   // M5.BtnB.wasPressed() — true once on edge
  bool powerButtonPressed();            // AXP side-button tap (GetBtnPress() == 0x02)
}}
