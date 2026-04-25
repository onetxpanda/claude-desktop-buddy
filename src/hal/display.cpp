#include "display.h"
#include <M5Unified.h>

static M5Canvas _spr(&M5.Display);

namespace hal { namespace display {

void begin() {
  M5.Display.setRotation(0);
  _spr.createSprite(135, 240);
}

M5GFX&       lcd()           { return M5.Display; }
M5Canvas&    sprite()        { return _spr; }
int  width()                 { return 135; }
int  height()                { return 240; }
void setRotation(uint8_t r)  { M5.Display.setRotation(r); }
void push()                  { _spr.pushSprite(0, 0); }

}}
