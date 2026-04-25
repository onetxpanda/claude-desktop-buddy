#include "power.h"
#include <M5Unified.h>

namespace hal { namespace power {

float busVoltage() { return M5.Power.getVBUSVoltage() / 1000.0f; }
float batVoltage() { return M5.Power.getBatteryVoltage() / 1000.0f; }
float batCurrent() { return M5.Power.getBatteryCurrent(); }

void setBrightness(uint8_t level) {
  M5.Display.setBrightness(20 + level * 20);
}

void setLcdPower(bool on) {
  if (on) M5.Display.wakeup();
  else    M5.Display.sleep();
}

void powerOff() { M5.Power.powerOff(); }

}}
