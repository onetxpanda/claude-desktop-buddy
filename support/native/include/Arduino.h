// Minimal Arduino-compat shim for the native (SDL) build. Only exposes the
// surface the firmware actually uses: Stream/Serial line input, millis/delay,
// digital-pin no-ops, ESP global with restart()/getFreeHeap().
//
// Force-included via -include in the emulator envs, so it must be safe in C
// translation units too — the C++-only bits (Stream, ESP, std headers) live
// behind `#ifdef __cplusplus`.
#pragma once

#include <stdint.h>
#include <stddef.h>
#include <stdarg.h>
#include <stdio.h>
#include <string.h>
#include <stdlib.h>
#include <unistd.h>
#include <time.h>

#define LOW    0
#define HIGH   1
#define INPUT  0
#define OUTPUT 1
#define INPUT_PULLUP 2

#ifdef __cplusplus
#include <chrono>
#include <thread>

template <typename A, typename B>
inline auto min(A a, B b) -> decltype(a < b ? a : b) { return a < b ? a : b; }
template <typename A, typename B>
inline auto max(A a, B b) -> decltype(a > b ? a : b) { return a > b ? a : b; }

inline void pinMode(int, int)            {}
inline void digitalWrite(int, int)       {}
inline int  digitalRead(int)             { return 0; }

inline uint32_t millis() {
  using clock = std::chrono::steady_clock;
  static const auto t0 = clock::now();
  return (uint32_t)std::chrono::duration_cast<std::chrono::milliseconds>(clock::now() - t0).count();
}

inline uint32_t micros() {
  using clock = std::chrono::steady_clock;
  static const auto t0 = clock::now();
  return (uint32_t)std::chrono::duration_cast<std::chrono::microseconds>(clock::now() - t0).count();
}

inline void delay(uint32_t ms) { std::this_thread::sleep_for(std::chrono::milliseconds(ms)); }
inline void delayMicroseconds(uint32_t us) { std::this_thread::sleep_for(std::chrono::microseconds(us)); }

// hal/display.cpp branches on psramFound() to pick 8bpp RGB332 (Core2) vs
// 16bpp (StickC). Reporting the same value here keeps the emulator on the
// same color-depth path, so B.3 color-tuning iteration is faithful.
inline bool psramFound() {
#if defined(NATIVE_TARGET_CORE2)
  return true;
#else
  return false;
#endif
}

class Stream {
public:
  virtual ~Stream() = default;
  virtual int  available() { return 0; }
  virtual int  read()      { return -1; }
  virtual int  peek()      { return -1; }
  virtual size_t write(uint8_t b) { return write(&b, 1); }
  virtual size_t write(const uint8_t* p, size_t n) { return fwrite(p, 1, n, stdout); }
  // Arduino's Stream also exposes char* overloads — match so callers like
  // Serial.write((const char*)buf, len) compile without casts.
  size_t write(const char* p, size_t n) { return write((const uint8_t*)p, n); }
  size_t write(char* p, size_t n)       { return write((const uint8_t*)p, n); }
  size_t print(const char* s)               { return s ? fwrite(s, 1, strlen(s), stdout) : 0; }
  size_t println(const char* s)             { size_t n = print(s); fputc('\n', stdout); return n + 1; }
  size_t println()                          { fputc('\n', stdout); return 1; }
  size_t printf(const char* fmt, ...) {
    va_list ap; va_start(ap, fmt);
    int n = vfprintf(stdout, fmt, ap);
    va_end(ap);
    return n < 0 ? 0 : (size_t)n;
  }
};

class HardwareSerial : public Stream {
public:
  void begin(unsigned long) {}
  void end() {}
};

extern HardwareSerial Serial;

class _ESPClass {
public:
  void restart() { fflush(stdout); _Exit(0); }
  uint32_t getFreeHeap() { return 200 * 1024; }
};
extern _ESPClass ESP;

#endif  // __cplusplus
