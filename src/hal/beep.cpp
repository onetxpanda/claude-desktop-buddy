#include "beep.h"
#include <M5StickCPlus.h>

namespace hal { namespace beep {

void begin()                              { M5.Beep.begin(); }
void tick()                               { M5.Beep.update(); }
void tone(uint16_t freq, uint16_t ms)     { M5.Beep.tone(freq, ms); }

}}
