// Stub Preferences. Reads return defaults so settings/stats land at their
// hard-coded fallbacks, which is what we want for a fresh emulator session.
#pragma once
#include <Arduino.h>

class Preferences {
public:
  bool     begin(const char*, bool = false) { return true; }
  void     end() {}
  void     clear() {}
  bool     remove(const char*) { return true; }
  size_t   putUChar(const char*, uint8_t)   { return 1; }
  size_t   putUShort(const char*, uint16_t) { return 2; }
  size_t   putUInt(const char*, uint32_t)   { return 4; }
  size_t   putULong(const char*, uint32_t)  { return 4; }
  size_t   putBool(const char*, bool)       { return 1; }
  size_t   putString(const char*, const char*) { return 0; }
  size_t   putBytes(const char*, const void*, size_t n) { return n; }
  uint8_t  getUChar(const char*, uint8_t d = 0)    { return d; }
  uint16_t getUShort(const char*, uint16_t d = 0)  { return d; }
  uint32_t getUInt(const char*, uint32_t d = 0)    { return d; }
  uint32_t getULong(const char*, uint32_t d = 0)   { return d; }
  bool     getBool(const char*, bool d = false)    { return d; }
  size_t   getString(const char*, char* out, size_t cap) { if (out && cap) out[0] = 0; return 0; }
  size_t   getBytes(const char*, void*, size_t)  { return 0; }
  bool     isKey(const char*) { return false; }
};
