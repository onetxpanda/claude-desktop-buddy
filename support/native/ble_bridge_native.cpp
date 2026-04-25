// Native build excludes src/ble_bridge.cpp and uses these no-op stubs.
// The desktop bridge is a hardware-radio thing — the emulator stays "not
// connected" so main.cpp's UI flows through the no-Claude path, and demo
// mode (toggleable from the menu) is the way to exercise live-data screens.

#include "ble_bridge.h"
#include <stddef.h>
#include <stdint.h>

void     bleInit(const char*)                 {}
bool     bleConnected()                       { return false; }
bool     bleSecure()                          { return false; }
uint32_t blePasskey()                         { return 0; }
void     bleClearBonds()                      {}
size_t   bleAvailable()                       { return 0; }
int      bleRead()                            { return -1; }
size_t   bleWrite(const uint8_t*, size_t n)   { return n; }
