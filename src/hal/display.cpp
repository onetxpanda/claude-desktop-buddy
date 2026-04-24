#include "display.h"
#include <M5StickCPlus.h>

extern TFT_eSprite spr;  // still lives in main.cpp during A.1..A.2.5

namespace hal { namespace display {

void begin()                 { /* sprite init still in main.cpp setup() */ }
TFT_eSPI&    lcd()           { return M5.Lcd; }
TFT_eSprite& sprite()        { return spr; }
int  width()                 { return 135; }
int  height()                { return 240; }
void setRotation(uint8_t r)  { M5.Lcd.setRotation(r); }
void push()                  { spr.pushSprite(0, 0); }

}}
