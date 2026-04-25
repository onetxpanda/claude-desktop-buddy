#include "beep.h"
#include <M5Unified.h>

namespace hal { namespace beep {

void begin()                              { /* M5.Speaker.begin() called by M5.begin() */ }
void tick()                               { /* M5.Speaker manages timing internally */ }
void tone(uint16_t freq, uint16_t ms)     { M5.Speaker.tone(freq, ms); }

}}
