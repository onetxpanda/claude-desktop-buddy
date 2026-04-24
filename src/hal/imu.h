#pragma once

namespace hal { namespace imu {
  void begin();
  void readAccel(float& ax, float& ay, float& az);
}}
