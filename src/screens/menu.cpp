#include "menu.h"
#include "menu_hints.h"
#include "../data.h"
#include <stdio.h>

namespace screen { namespace menu {

static const char* items[] = { "settings", "turn off", "help", "about", "demo", "close" };
static constexpr uint8_t N = 6;
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
  for (int i = 0; i < N; i++) {
    bool sel = (i == selIdx);
    spr.setTextColor(sel ? p.text : p.textDim, MENU_PANEL);
    spr.setCursor(mx + 6, my + 8 + i * 14);
    spr.print(sel ? "> " : "  ");
    spr.print(items[i]);
    if (i == 4) spr.print(dataDemo() ? "  on" : "  off");
  }
  drawMenuHints(p, mx, mw, my + mh - 12);
}

}}
