#pragma once

namespace hal {
  // M5.begin() + display/beep/imu init. Call once from setup().
  void begin();
  // M5.update() + per-frame bookkeeping. Call once per loop().
  void tick();
}
