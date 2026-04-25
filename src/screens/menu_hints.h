#pragma once
// Shared footer-hint renderer for overlay menu panels.
// Include this in menu.cpp, settings.cpp, reset.cpp only.

#include "../hal/display.h"
#include "../character.h"

extern M5Canvas& canvas;

static const uint16_t MENU_PANEL = 0x2104;   // overlay panel background
static const int      MENU_HINT_H = 14;

static void drawMenuHints(const Palette& p, int mx, int mw, int hy,
                          const char* downLbl = "A", const char* rightLbl = "B") {
  canvas.drawFastHLine(mx + 6, hy - 4, mw - 12, p.textDim);
  canvas.setTextColor(p.textDim, MENU_PANEL);
  int x = mx + 8;
  canvas.setCursor(x, hy); canvas.print(downLbl);
  x += strlen(downLbl) * 6 + 4;
  canvas.fillTriangle(x, hy + 1, x + 6, hy + 1, x + 3, hy + 6, p.textDim);
  x = mx + mw / 2 + 4;
  canvas.setCursor(x, hy); canvas.print(rightLbl);
  x += strlen(rightLbl) * 6 + 4;
  canvas.fillTriangle(x, hy, x, hy + 6, x + 5, hy + 3, p.textDim);
}
