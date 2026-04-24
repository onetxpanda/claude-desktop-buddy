#include "passkey.h"
#include "../hal/display.h"
#include "../ble_bridge.h"
#include "../character.h"
#include <stdio.h>

// Declared in main.cpp
extern TFT_eSprite& spr;

namespace screen { namespace passkey {

void draw() {
  static constexpr int W = 135;  // screen width
  const Palette& p = characterPalette();
  spr.fillSprite(p.bg);
  spr.setTextSize(1);
  spr.setTextColor(p.textDim, p.bg);
  spr.setCursor(8, 56);  spr.print("BLUETOOTH PAIRING");
  spr.setCursor(8, 184); spr.print("enter on desktop:");
  spr.setTextSize(3);
  spr.setTextColor(p.text, p.bg);
  char b[8]; snprintf(b, sizeof(b), "%06lu", (unsigned long)blePasskey());
  spr.setCursor((W - 18 * 6) / 2, 110);
  spr.print(b);
}

}}
