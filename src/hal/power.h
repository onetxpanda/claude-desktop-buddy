#pragma once
#include <stdint.h>

namespace hal { namespace power {
  float busVoltage();                 // VBus in volts (> 4.0 = USB attached)
  float batVoltage();                 // battery V
  float batCurrent();                 // battery current (mA)
  float axpTemp();                    // AXP192 die temperature (°C)
  void  setBrightness(uint8_t level); // 0..5 — ScreenBreath(20 + level*20)
  void  setLcdPower(bool on);         // LDO2 rail — LCD backlight/power
  void  powerOff();                   // hard shutdown
}}
