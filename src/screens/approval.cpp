#include "approval.h"
#include <M5Unified.h>
#include "../hal/display.h"
#include "../character.h"
#include "../data.h"
#include <stdio.h>
#include <cstring>

extern M5GFX& canvas;
extern TamaState tama;
extern uint32_t promptArrivedMs;
extern bool responseSent;

// Wrappers provided by main.cpp (avoid pulling in stats.h which is single-TU)
extern void approvalDoApprove();
extern void approvalDoDeny();

// Colors used across multiple UI surfaces
static const uint16_t HOT   = 0xFA20;   // red-orange: warnings, impatience, deny

namespace screen { namespace approval {

void draw() {
  const Palette& p = characterPalette();
  const int AREA = 78;
  canvas.fillRect(0, hal::display::height() - AREA, hal::display::width(), AREA, p.bg);
  canvas.drawFastHLine(0, hal::display::height() - AREA, hal::display::width(), p.textDim);

  canvas.setTextSize(hal::display::isLarge() ? 2 : 1);
  canvas.setTextColor(p.textDim, p.bg);
  canvas.setCursor(4, hal::display::height() - AREA + 4);
  uint32_t waited = (millis() - promptArrivedMs) / 1000;
  if (waited >= 10) canvas.setTextColor(HOT, p.bg);
  canvas.printf("approve? %lus", (unsigned long)waited);

  // Size 2 only if it fits one line (~10 chars at 12px on 135px screen)
  int toolLen = strlen(tama.promptTool);
  canvas.setTextColor(p.text, p.bg);
  canvas.setTextSize(toolLen <= 10 ? (hal::display::isLarge() ? 3 : 2) : (hal::display::isLarge() ? 2 : 1));
  canvas.setCursor(4, hal::display::height() - AREA + (toolLen <= 10 ? 14 : 18));
  canvas.print(tama.promptTool);
  canvas.setTextSize(1);

  // Hint wraps at ~21 chars to two lines under the tool name
  canvas.setTextColor(p.textDim, p.bg);
  int hlen = strlen(tama.promptHint);
  canvas.setCursor(4, hal::display::height() - AREA + 34);
  canvas.printf("%.21s", tama.promptHint);
  if (hlen > 21) {
    canvas.setCursor(4, hal::display::height() - AREA + 42);
    canvas.printf("%.21s", tama.promptHint + 21);
  }

  canvas.setTextSize(hal::display::isLarge() ? 2 : 1);
  if (responseSent) {
    canvas.setTextColor(p.textDim, p.bg);
    canvas.setCursor(4, hal::display::height() - (hal::display::isLarge() ? 20 : 12));
    canvas.print("sent...");
  } else {
    canvas.setTextColor(GREEN, p.bg);
    canvas.setCursor(4, hal::display::height() - (hal::display::isLarge() ? 20 : 12));
    canvas.print("A: approve");
    canvas.setTextColor(HOT, p.bg);
    canvas.setCursor(hal::display::width() - (hal::display::isLarge() ? 84 : 48),
                     hal::display::height() - (hal::display::isLarge() ? 20 : 12));
    canvas.print("B: deny");
  }
  canvas.setTextSize(1);
}

bool handleButton(Btn b, BtnEvent e) {
  if (e != BtnEvent::Tap) return false;
  if (b == Btn::A) { approvalDoApprove(); return true; }
  if (b == Btn::B) { approvalDoDeny();    return true; }
  return false;
}

}}
