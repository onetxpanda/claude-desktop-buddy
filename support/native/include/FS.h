// Stub Arduino FS.h for the native build. The firmware's only File usage is
// gated on LittleFS having content, which the stub LittleFS reports as empty.
#pragma once
#include <Arduino.h>

class File {
public:
  operator bool() const { return _ok; }
  bool isDirectory() const { return _dir; }
  const char* name() const { return ""; }
  size_t size() const { return 0; }
  size_t position() const { return 0; }
  // ArduinoJson's Reader<File> calls the no-arg read(); -1 means EOF.
  int    read() { return -1; }
  size_t read(uint8_t*, size_t) { return 0; }
  size_t write(const uint8_t*, size_t) { return 0; }
  bool seek(size_t) { return false; }
  void close() { _ok = false; }
  File openNextFile() { return File(); }
  File() = default;
  File(bool ok, bool dir) : _ok(ok), _dir(dir) {}
private:
  bool _ok = false;
  bool _dir = false;
};
