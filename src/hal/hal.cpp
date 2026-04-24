#include "hal.h"
#include "display.h"
#include "beep.h"
#include <M5StickCPlus.h>

namespace hal {

void begin() {
  M5.begin();
  display::begin();
  M5.Imu.Init();
  beep::begin();
}

void tick() {
  M5.update();
  beep::tick();
}

} // namespace hal
