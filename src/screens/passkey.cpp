#include "passkey.h"
#include "../hal/display.h"
#include "../ble_bridge.h"
#include "../character.h"
#include <stdio.h>

// Declared in main.cpp
extern M5Canvas& canvas;

namespace screen { namespace passkey {

void draw() {
  const int W = hal::display::width();
  const bool lg = hal::display::isLarge();
  const Palette& p = characterPalette();
  canvas.fillSprite(p.bg);
  canvas.setTextSize(lg ? 2 : 1);
  canvas.setTextColor(p.textDim, p.bg);
  canvas.setCursor(8, 56);  canvas.print("BLUETOOTH PAIRING");
  canvas.setCursor(8, 184); canvas.print("enter on desktop:");
  const int pkSize = lg ? 5 : 3;
  canvas.setTextSize(pkSize);
  canvas.setTextColor(p.text, p.bg);
  char b[8]; snprintf(b, sizeof(b), "%06lu", (unsigned long)blePasskey());
  // Each char is pkSize*6 px wide; 6 digits total → center in W
  canvas.setCursor((W - pkSize * 6 * 6) / 2, 110);
  canvas.print(b);
  canvas.setTextSize(1);
}

}}
