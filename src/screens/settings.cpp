#include "settings.h"
#include "menu_hints.h"
#include "../stats.h"
#include "../buddy.h"
#include <stdio.h>

extern uint8_t brightLevel;
extern bool    gifAvailable;
extern bool    buddyMode;

namespace screen { namespace settings {

static const char* items[] = {
  "brightness", "sound", "bluetooth", "wifi", "led",
  "transcript", "clock rot", "ascii pet", "reset", "back"
};
static constexpr uint8_t N = 10;
static uint8_t selIdx = 0;

uint8_t selected()             { return selIdx; }
void    setSelected(uint8_t i) { selIdx = i % N; }
uint8_t itemCount()            { return N; }

void draw() {
  const Palette& p = characterPalette();
  int mw = 118, mh = 16 + N * 14 + MENU_HINT_H;
  int mx = (hal::display::width() - mw) / 2, my = (hal::display::height() - mh) / 2;
  spr.fillRoundRect(mx, my, mw, mh, 4, MENU_PANEL);
  spr.drawRoundRect(mx, my, mw, mh, 4, p.textDim);
  spr.setTextSize(1);
  Settings& s = ::settings();
  bool vals[] = { s.sound, s.bt, s.wifi, s.led, s.hud };
  for (int i = 0; i < N; i++) {
    bool sel = (i == selIdx);
    spr.setTextColor(sel ? p.text : p.textDim, MENU_PANEL);
    spr.setCursor(mx + 6, my + 8 + i * 14);
    spr.print(sel ? "> " : "  ");
    spr.print(items[i]);
    spr.setCursor(mx + mw - 36, my + 8 + i * 14);
    spr.setTextColor(p.textDim, MENU_PANEL);
    if (i == 0) {
      spr.printf("%u/4", brightLevel);
    } else if (i >= 1 && i <= 5) {
      spr.setTextColor(vals[i-1] ? GREEN : p.textDim, MENU_PANEL);
      spr.print(vals[i-1] ? " on" : "off");
    } else if (i == 6) {
      static const char* const RN[] = { "auto", "port", "land" };
      spr.print(RN[s.clockRot]);
    } else if (i == 7) {
      uint8_t total = buddySpeciesCount() + (gifAvailable ? 1 : 0);
      uint8_t pos   = buddyMode ? buddySpeciesIdx() + 1 : total;
      spr.printf("%u/%u", pos, total);
    }
  }
  drawMenuHints(p, mx, mw, my + mh - 12, "Next", "Change");
}

}}
