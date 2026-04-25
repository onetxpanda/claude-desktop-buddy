#pragma once
#include <stdint.h>

namespace hal { namespace power {
  float busVoltage();
  float batVoltage();
  float batCurrent();
  void  setBrightness(uint8_t level);
  void  setLcdPower(bool on);
  void  powerOff();
}}
