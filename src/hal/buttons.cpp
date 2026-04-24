#include "buttons.h"
#include <M5StickCPlus.h>

namespace hal { namespace buttons {

bool pressedA()             { return M5.BtnA.isPressed(); }
bool pressedB()             { return M5.BtnB.isPressed(); }
bool heldA(uint16_t ms)     { return M5.BtnA.pressedFor(ms); }
bool powerButtonPressed()   { return M5.Axp.GetBtnPress() == 0x02; }

}}
