#include "imu.h"
#include <M5StickCPlus.h>

namespace hal { namespace imu {

void readAccel(float& ax, float& ay, float& az) {
  M5.Imu.getAccelData(&ax, &ay, &az);
}

}}
