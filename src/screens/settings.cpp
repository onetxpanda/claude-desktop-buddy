#include "settings.h"
#include "menu_hints.h"
#include "../stats.h"
#include "../buddy.h"
#include <stdio.h>

extern void beep(uint16_t freq, uint16_t dur);

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

bool handleButton(Btn b, BtnEvent e) {
  // A-tap: advance selection; B-tap: activate item (falls through to main.cpp)
  if (b == Btn::A && e == BtnEvent::Tap) { beep(1800, 30); selIdx = (selIdx + 1) % N; return true; }
  return false;
}

void draw() {
  const Palette& p = characterPalette();
  const bool lg = hal::display::isLarge();
  // itemH=20 keeps the 10-item panel under 240px tall on Core2:
  //   16 + 10*20 + 14 = 230. itemH=22 (matching menu.cpp) overflowed.
  const int itemH  = lg ? 20 : 14;
  const int valOff = lg ? 70 : 36;   // value column inset from panel right edge
  int mw = lg ? 240 : 118;
  int mh = 16 + N * itemH + MENU_HINT_H;
  int mx = (hal::display::width() - mw) / 2, my = (hal::display::height() - mh) / 2;
  canvas.fillRoundRect(mx, my, mw, mh, 4, MENU_PANEL);
  canvas.drawRoundRect(mx, my, mw, mh, 4, p.textDim);
  canvas.setTextSize(lg ? 2 : 1);
  Settings& s = ::settings();
  bool vals[] = { s.sound, s.bt, s.wifi, s.led, s.hud };
  for (int i = 0; i < N; i++) {
    bool sel = (i == selIdx);
    canvas.setTextColor(sel ? p.text : p.textDim, MENU_PANEL);
    canvas.setCursor(mx + 6, my + 8 + i * itemH);
    canvas.print(sel ? "> " : "  ");
    canvas.print(items[i]);
    canvas.setCursor(mx + mw - valOff, my + 8 + i * itemH);
    canvas.setTextColor(p.textDim, MENU_PANEL);
    if (i == 0) {
      canvas.printf("%u/4", brightLevel);
    } else if (i >= 1 && i <= 5) {
      canvas.setTextColor(vals[i-1] ? GREEN : p.textDim, MENU_PANEL);
      canvas.print(vals[i-1] ? " on" : "off");
    } else if (i == 6) {
      static const char* const RN[] = { "auto", "port", "land" };
      canvas.print(RN[s.clockRot]);
    } else if (i == 7) {
      uint8_t total = buddySpeciesCount() + (gifAvailable ? 1 : 0);
      uint8_t pos   = buddyMode ? buddySpeciesIdx() + 1 : total;
      canvas.printf("%u/%u", pos, total);
    }
  }
  canvas.setTextSize(1);
  drawMenuHints(p, mx, mw, my + mh - 12, "Next", "Change");
}

}}
