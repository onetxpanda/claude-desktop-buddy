// Native (SDL emulator) stub for arduino-esp32's Update.h. The real
// Update class talks to the OTA partition machinery via esp_ota_*; on
// host there's nothing to flash, so all operations are no-ops that
// claim success. Lets src/ota.cpp compile + run protocol-only state
// machine tests in the emulator without pulling in flash code.
#pragma once
#include <stddef.h>
#include <stdint.h>

#define U_FLASH 0
#define U_SPIFFS 100

class _UpdateClass {
public:
  bool   begin(size_t /*size*/, int /*command*/ = U_FLASH) { return true; }
  size_t write(const uint8_t* /*data*/, size_t n)          { return n; }
  bool   end(bool /*evenIfRemaining*/ = true)              { return true; }
  bool   abort()                                            { return true; }
  size_t size() const                                       { return 0; }
  const char* errorString() const                           { return "stub"; }
};

extern _UpdateClass Update;
