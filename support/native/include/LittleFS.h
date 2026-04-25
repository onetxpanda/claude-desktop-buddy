// Stub LittleFS that always reports an empty filesystem. Lets character.cpp,
// xfer.h, and main.cpp's reset path compile and behave as "no GIFs installed,
// nothing to delete." For native screenshot work the ASCII buddy renderers
// are sufficient.
#pragma once
#include <FS.h>

class _LittleFSClass {
public:
  bool begin(bool = false) { return true; }
  bool format()            { return true; }
  File open(const char*, const char* = "r") { return File(); }
  bool remove(const char*) { return true; }
  bool rmdir(const char*)  { return true; }
  bool mkdir(const char*)  { return true; }
  bool exists(const char*) { return false; }
  size_t totalBytes() { return 0; }
  size_t usedBytes()  { return 0; }
};

extern _LittleFSClass LittleFS;
