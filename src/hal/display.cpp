#include "display.h"
#include <M5Unified.h>

// Standard M5Canvas pattern. Default allocation is DMA-capable internal
// RAM — coherent with M5GFX's pushSprite path, no PSRAM gymnastics. At
// 16bpp full-color, 320×240×2 = 150 KB; fits alongside NimBLE-Arduino
// (which is ~100 KB lighter than the Bluedroid stack the original code
// budgeted around).
static M5Canvas _spr(&M5.Display);

namespace hal { namespace display {

void begin() {
  M5.Display.setColorDepth(16);
  _spr.setColorDepth(16);
  _spr.createSprite(M5.Display.width(), M5.Display.height());
}

M5GFX&     lcd()             { return M5.Display; }
M5Canvas&  sprite()          { return _spr; }
int  width()                 { return M5.Display.width(); }
int  height()                { return M5.Display.height(); }
void setRotation(uint8_t r)  { M5.Display.setRotation(r); }
void push()                  { _spr.pushSprite(0, 0); }
bool isLarge()               { return M5.Display.width() >= 320; }

}}
