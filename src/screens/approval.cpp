#include "approval.h"
#include <M5StickCPlus.h>
#include "../hal/display.h"
#include "../character.h"
#include "../data.h"
#include <stdio.h>
#include <cstring>

extern TFT_eSprite& spr;
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
  spr.fillRect(0, hal::display::height() - AREA, hal::display::width(), AREA, p.bg);
  spr.drawFastHLine(0, hal::display::height() - AREA, hal::display::width(), p.textDim);

  spr.setTextSize(1);
  spr.setTextColor(p.textDim, p.bg);
  spr.setCursor(4, hal::display::height() - AREA + 4);
  uint32_t waited = (millis() - promptArrivedMs) / 1000;
  if (waited >= 10) spr.setTextColor(HOT, p.bg);
  spr.printf("approve? %lus", (unsigned long)waited);

  // Size 2 only if it fits one line (~10 chars at 12px on 135px screen)
  int toolLen = strlen(tama.promptTool);
  spr.setTextColor(p.text, p.bg);
  spr.setTextSize(toolLen <= 10 ? 2 : 1);
  spr.setCursor(4, hal::display::height() - AREA + (toolLen <= 10 ? 14 : 18));
  spr.print(tama.promptTool);
  spr.setTextSize(1);

  // Hint wraps at ~21 chars to two lines under the tool name
  spr.setTextColor(p.textDim, p.bg);
  int hlen = strlen(tama.promptHint);
  spr.setCursor(4, hal::display::height() - AREA + 34);
  spr.printf("%.21s", tama.promptHint);
  if (hlen > 21) {
    spr.setCursor(4, hal::display::height() - AREA + 42);
    spr.printf("%.21s", tama.promptHint + 21);
  }

  if (responseSent) {
    spr.setTextColor(p.textDim, p.bg);
    spr.setCursor(4, hal::display::height() - 12);
    spr.print("sent...");
  } else {
    spr.setTextColor(GREEN, p.bg);
    spr.setCursor(4, hal::display::height() - 12);
    spr.print("A: approve");
    spr.setTextColor(HOT, p.bg);
    spr.setCursor(hal::display::width() - 48, hal::display::height() - 12);
    spr.print("B: deny");
  }
}

bool handleButton(Btn b, BtnEvent e) {
  if (e != BtnEvent::Tap) return false;
  if (b == Btn::A) { approvalDoApprove(); return true; }
  if (b == Btn::B) { approvalDoDeny();    return true; }
  return false;
}

}}
