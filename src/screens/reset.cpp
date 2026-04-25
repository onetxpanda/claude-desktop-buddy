#include "reset.h"
#include "menu_hints.h"
#include <Arduino.h>

static const uint16_t RESET_HOT = 0xFA20;   // red-orange: warnings, impatience, deny

namespace screen { namespace reset {

static const char* items[] = { "delete char", "factory reset", "back" };
static constexpr uint8_t N = 3;
static uint8_t  selIdx         = 0;
static uint8_t  confirmIdx     = 0xFF;
static uint32_t confirmUntilMs = 0;

uint8_t  selected()             { return selIdx; }
void     setSelected(uint8_t i) { selIdx = i % N; }
uint8_t  itemCount()            { return N; }

uint8_t  lastConfirmIdx()       { return confirmIdx; }
uint32_t confirmDeadline()      { return confirmUntilMs; }

void setLastConfirm(uint8_t idx, uint32_t deadlineMs) {
  confirmIdx     = idx;
  confirmUntilMs = deadlineMs;
}

void draw() {
  const Palette& p = characterPalette();
  int mw = 118, mh = 16 + N * 14 + MENU_HINT_H;
  int mx = (hal::display::width() - mw) / 2, my = (hal::display::height() - mh) / 2;
  spr.fillRoundRect(mx, my, mw, mh, 4, MENU_PANEL);
  spr.drawRoundRect(mx, my, mw, mh, 4, RESET_HOT);
  spr.setTextSize(1);
  for (int i = 0; i < N; i++) {
    bool sel = (i == selIdx);
    spr.setTextColor(sel ? p.text : p.textDim, MENU_PANEL);
    spr.setCursor(mx + 6, my + 8 + i * 14);
    spr.print(sel ? "> " : "  ");
    bool armed = (i == confirmIdx) &&
                 (int32_t)(millis() - confirmUntilMs) < 0;
    if (armed) spr.setTextColor(RESET_HOT, MENU_PANEL);
    spr.print(armed ? "really?" : items[i]);
  }
  drawMenuHints(p, mx, mw, my + mh - 12);
}

}}
