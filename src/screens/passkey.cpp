#include "passkey.h"
#include "../hal/display.h"
#include "../ble_bridge.h"
#include "../character.h"
#include <stdio.h>

// Declared in main.cpp
extern M5Canvas& canvas;

namespace screen { namespace passkey {

void draw() {
  static constexpr int W = 135;  // screen width
  const Palette& p = characterPalette();
  canvas.fillSprite(p.bg);
  canvas.setTextSize(1);
  canvas.setTextColor(p.textDim, p.bg);
  canvas.setCursor(8, 56);  canvas.print("BLUETOOTH PAIRING");
  canvas.setCursor(8, 184); canvas.print("enter on desktop:");
  canvas.setTextSize(3);
  canvas.setTextColor(p.text, p.bg);
  char b[8]; snprintf(b, sizeof(b), "%06lu", (unsigned long)blePasskey());
  canvas.setCursor((W - 18 * 6) / 2, 110);
  canvas.print(b);
}

}}
