#include "reset.h"
#include "menu_hints.h"
#include <Arduino.h>

extern void beep(uint16_t freq, uint16_t dur);

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

bool handleButton(Btn b, BtnEvent e) {
  // A-tap: advance selection; B-tap: execute reset action (falls through to main.cpp)
  if (b == Btn::A && e == BtnEvent::Tap) {
    beep(1800, 30);
    selIdx = (selIdx + 1) % N;
    // Scrolling away clears the arm
    confirmIdx = 0xFF;
    confirmUntilMs = 0;
    return true;
  }
  return false;
}

uint8_t  lastConfirmIdx()       { return confirmIdx; }
uint32_t confirmDeadline()      { return confirmUntilMs; }

void setLastConfirm(uint8_t idx, uint32_t deadlineMs) {
  confirmIdx     = idx;
  confirmUntilMs = deadlineMs;
}

void draw() {
  const Palette& p = characterPalette();
  const bool lg = hal::display::isLarge();
  const int itemH = lg ? 22 : 14;
  int mw = lg ? 180 : 118, mh = 16 + N * itemH + MENU_HINT_H;
  int mx = (hal::display::width() - mw) / 2, my = (hal::display::height() - mh) / 2;
  canvas.fillRoundRect(mx, my, mw, mh, 4, MENU_PANEL);
  canvas.drawRoundRect(mx, my, mw, mh, 4, RESET_HOT);
  canvas.setTextSize(lg ? 2 : 1);
  for (int i = 0; i < N; i++) {
    bool sel = (i == selIdx);
    canvas.setTextColor(sel ? p.text : p.textDim, MENU_PANEL);
    canvas.setCursor(mx + 6, my + 8 + i * itemH);
    canvas.print(sel ? "> " : "  ");
    bool armed = (i == confirmIdx) &&
                 (int32_t)(millis() - confirmUntilMs) < 0;
    if (armed) canvas.setTextColor(RESET_HOT, MENU_PANEL);
    canvas.print(armed ? "really?" : items[i]);
  }
  canvas.setTextSize(1);
  drawMenuHints(p, mx, mw, my + mh - 12);
}

}}
