#include "menu.h"
#include "menu_hints.h"
#include "../data.h"
#include <stdio.h>

extern void beep(uint16_t freq, uint16_t dur);

namespace screen { namespace menu {

static const char* items[] = { "settings", "turn off", "help", "about", "demo", "close" };
static constexpr uint8_t N = 6;
static uint8_t selIdx = 0;

uint8_t selected()             { return selIdx; }
void    setSelected(uint8_t i) { selIdx = i % N; }
uint8_t itemCount()            { return N; }

bool handleButton(Btn b, BtnEvent e) {
  // A-tap: advance selection (navigation only; activation falls through to main.cpp)
  if (b == Btn::A && e == BtnEvent::Tap) { beep(1800, 30); selIdx = (selIdx + 1) % N; return true; }
  // B-tap: confirm/activate — let main.cpp handle via menuConfirm()
  return false;
}

void draw() {
  const Palette& p = characterPalette();
  int mw = 118, mh = 16 + N * 14 + MENU_HINT_H;
  int mx = (hal::display::width() - mw) / 2, my = (hal::display::height() - mh) / 2;
  canvas.fillRoundRect(mx, my, mw, mh, 4, MENU_PANEL);
  canvas.drawRoundRect(mx, my, mw, mh, 4, p.textDim);
  canvas.setTextSize(1);
  for (int i = 0; i < N; i++) {
    bool sel = (i == selIdx);
    canvas.setTextColor(sel ? p.text : p.textDim, MENU_PANEL);
    canvas.setCursor(mx + 6, my + 8 + i * 14);
    canvas.print(sel ? "> " : "  ");
    canvas.print(items[i]);
    if (i == 4) canvas.print(dataDemo() ? "  on" : "  off");
  }
  drawMenuHints(p, mx, mw, my + mh - 12);
}

}}
