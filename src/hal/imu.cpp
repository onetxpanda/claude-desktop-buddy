#include "imu.h"
#include <M5Unified.h>

namespace hal { namespace imu {

void begin() { M5.Imu.begin(); }

void readAccel(float& ax, float& ay, float& az) {
  auto d = M5.Imu.getImuData();
  ax = d.accel.x;
  ay = d.accel.y;
  az = d.accel.z;
}

}}
