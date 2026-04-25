#include "buttons.h"
#include <M5Unified.h>

namespace hal { namespace buttons {

bool pressedA()             { return M5.BtnA.isPressed(); }
bool pressedB()             { return M5.BtnB.isPressed(); }
bool heldA(uint16_t ms)     { return M5.BtnA.pressedFor(ms); }
bool wasReleasedA()         { return M5.BtnA.wasReleased(); }
bool wasPressedB()          { return M5.BtnB.wasPressed(); }
bool powerButtonPressed()   { return M5.BtnPWR.wasClicked(); }

}}
