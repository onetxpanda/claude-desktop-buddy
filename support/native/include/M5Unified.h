// Faithful-shape M5Unified shim for the native (SDL) emulator build.
//
// Real M5Unified can't be compiled on the host — it pulls in Wire, ESP-IDF
// BLE/NVS, AXP192/MPU6886 register access, etc. So we mimic just the API
// surface our firmware uses, backed by M5GFX (real SDL backend) and trivial
// in-process fakes. The win: src/hal/*.cpp compiles unmodified across both
// the on-device and emulator builds, and any future hal/ extension that
// touches M5.X automatically works in the emulator with no extra plumbing.
//
// Surface covered (everything the firmware actually calls):
//   M5.begin() / M5.update()
//   M5.Display                — real M5GFX (LovyanGFX SDL backend)
//   M5.BtnA / M5.BtnB / M5.BtnPWR — keyboard-backed: A/Left, B/Right, P
//   M5.Imu.begin / .getImuData    — returns "upright" gravity vector
//   M5.Speaker.tone               — no-op
//   M5.Power.{getVBUSVoltage,getBatteryVoltage,getBatteryCurrent,powerOff}
//   M5.Rtc.{getDateTime,setDateTime}  — backed by host clock (set is a no-op)
//
// Anything outside this list will fail to compile on the native env, which is
// the right signal that the shim needs to grow.

#pragma once

#include <Arduino.h>
#include <M5GFX.h>
#include <esp_mac.h>     // matches the device path: ESP-IDF's esp_mac.h is
                         // pulled in transitively via M5Unified there.
#include <esp_random.h>
#include <stdint.h>
#include <stdlib.h>
#include <time.h>

namespace m5 {

class Button_Class {
public:
  bool isPressed()                 const { return _curr; }
  bool wasPressed()                const { return !_prev && _curr; }
  bool wasReleased()               const { return _prev && !_curr; }
  bool wasClicked()                const { return wasReleased(); }
  bool pressedFor(uint32_t ms)     const { return _curr && (millis() - _pressedSinceMs) >= ms; }

  // Internal — driven by M5_Class::update().
  void _set(bool down) {
    _prev = _curr;
    if (down && !_curr) _pressedSinceMs = millis();
    _curr = down;
  }
private:
  bool     _curr = false, _prev = false;
  uint32_t _pressedSinceMs = 0;
};

struct vec3f_t { float x, y, z; };
struct imu_data_t { vec3f_t accel; vec3f_t gyro; vec3f_t mag; };

class IMU_Class {
public:
  bool       begin()                 { return true; }
  imu_data_t getImuData() const {
    imu_data_t d{};
    d.accel = { 0.0f, 0.0f, 1.0f };   // upright
    return d;
  }
};

class Speaker_Class {
public:
  void tone(uint16_t, uint16_t) {}
};

class Power_Class {
public:
  uint16_t getVBUSVoltage()    const { return 4200; }   // 4.2V — emulator stays "on USB"
  uint16_t getBatteryVoltage() const { return 4000; }
  float    getBatteryCurrent() const { return 0.0f; }
  void     powerOff()                { _Exit(0); }
};

struct rtc_time_t { uint8_t hours, minutes, seconds; };
struct rtc_date_t { uint8_t weekDay, month, date; uint16_t year; };
struct local_datetime_t {
  rtc_time_t time;
  rtc_date_t date;
};

class RTC_Class {
public:
  local_datetime_t getDateTime() const {
    local_datetime_t dt{};
    time_t now = ::time(nullptr);
    struct tm lt; localtime_r(&now, &lt);
    dt.time.hours   = (uint8_t)lt.tm_hour;
    dt.time.minutes = (uint8_t)lt.tm_min;
    dt.time.seconds = (uint8_t)lt.tm_sec;
    dt.date.weekDay = (uint8_t)lt.tm_wday;
    dt.date.month   = (uint8_t)(lt.tm_mon + 1);
    dt.date.date    = (uint8_t)lt.tm_mday;
    dt.date.year    = (uint16_t)(lt.tm_year + 1900);
    return dt;
  }
  void setDateTime(const local_datetime_t&) {}
};

}  // namespace m5

class M5_Class {
public:
  M5GFX             Display;
  m5::Button_Class  BtnA, BtnB, BtnPWR;
  m5::IMU_Class     Imu;
  m5::Speaker_Class Speaker;
  m5::Power_Class   Power;
  m5::RTC_Class     Rtc;

  // Defined in support/native/m5unified_shim.cpp.
  void begin();
  void update();
};

extern M5_Class M5;
