#include "display.h"
#include <M5Unified.h>

// Off-screen frame buffer. Drawing during a frame goes here; push() blits
// it to the LCD in one shot. Constructed with M5.Display as parent so
// M5Canvas's parent-aware constructor sets _psram=true — the framebuffer
// lives in PSRAM, where 150 KB at 16bpp is trivially available. M5GFX
// detects the PSRAM allocation and pushes via CPU-driven SPI (LGFX_Sprite
// .hpp:424 passes use_dma=false for SPIRAM-backed sprites), so the CPU
// reads pixels through the cache it just wrote into — no PSRAM/DMA
// coherency hole, no white/green lines.
static M5Canvas _spr(&M5.Display);

namespace hal { namespace display {

void begin() {
  // Core2's ILI9342C ships with rgb_order=false in M5Unified's
  // Panel_M5StackCore2 config, which sends MAD_BGR in MADCTL — telling
  // the panel to interpret incoming pixel bytes as BGR. M5GFX's color
  // converter outputs RGB565, so on hardware we get an R↔B swap (the
  // light blue-green buddy reads as orange). Flipping rgb_order to true
  // emits MAD_RGB, matching the data the rest of the lib sends.
  // setRotation re-emits MADCTL so the change takes effect.
  auto* p = M5.Display.panel();
  auto cfg = p->config();
  if (!cfg.rgb_order) {
    cfg.rgb_order = true;
    p->config(cfg);
    M5.Display.setRotation(M5.Display.getRotation());
  }

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
