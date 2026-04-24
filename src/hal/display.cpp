#include "display.h"
#include <M5StickCPlus.h>

// Sprite owned here. file-scope static — initialized at program startup,
// before main.cpp's reference binds.
static TFT_eSprite _spr(&M5.Lcd);

namespace hal { namespace display {

void begin() {
  M5.Lcd.setRotation(0);
  _spr.createSprite(135, 240);
}

TFT_eSPI&    lcd()           { return M5.Lcd; }
TFT_eSprite& sprite()        { return _spr; }
int  width()                 { return 135; }
int  height()                { return 240; }
void setRotation(uint8_t r)  { M5.Lcd.setRotation(r); }
void push()                  { _spr.pushSprite(0, 0); }

}}
