#include "imu.h"
#include <M5StickCPlus.h>
#undef imu

namespace hal { namespace imu {

void begin() { M5.Imu.Init(); }

void readAccel(float& ax, float& ay, float& az) {
  M5.Imu.getAccelData(&ax, &ay, &az);
}

}}
