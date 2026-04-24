#include "hal.h"
#include "display.h"
#include "beep.h"
#include "imu.h"
#include <M5StickCPlus.h>
#undef imu

namespace hal {

void begin() {
  M5.begin();
  display::begin();
  imu::begin();
  beep::begin();
}

void tick() {
  M5.update();
  beep::tick();
}

} // namespace hal
