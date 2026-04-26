#include "clock.h"
#include "../hal/display.h"
#include "../character.h"
#include "../buddy.h"
#include <stdio.h>

extern M5GFX& canvas;
extern bool buddyMode;
extern uint8_t activeState;  // PersonaState enum defined in main.cpp

namespace screen { namespace clock {

static uint8_t paintedOrient = 0;
static uint8_t lastSec       = 0xFF;

static const char* const MON[] = {
  "Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"
};
static const char* const DOW[] = {"Sun","Mon","Tue","Wed","Thu","Fri","Sat"};

// Local helper that was clockDow() in main.cpp.
static uint8_t dow(const hal::rtc::Date& d) { return d.weekday % 7; }

void draw(uint8_t orient,
          const hal::rtc::Time& t,
          const hal::rtc::Date& d) {
  const Palette& p = characterPalette();
  char hm[6]; snprintf(hm, sizeof(hm), "%02u:%02u", t.h, t.m);
  char ss[4]; snprintf(ss, sizeof(ss), ":%02u", t.s);
  uint8_t mi = (d.month >= 1 && d.month <= 12) ? d.month - 1 : 0;
  char dl[8]; snprintf(dl, sizeof(dl), "%s %02u", MON[mi], d.day);

  if (orient == 0) {
    paintedOrient = 0;
    // Bottom half — buddy naturally lives at y=0..82, GIF peeks at top
    // via peek mode. Clearing from 90 leaves both untouched.
    canvas.fillRect(0, 90, hal::display::width(), hal::display::height() - 90, p.bg);
    canvas.setTextDatum(MC_DATUM);
    canvas.setTextSize(4); canvas.setTextColor(p.text, p.bg);    canvas.drawString(hm, hal::display::width() / 2, 140);
    canvas.setTextSize(2); canvas.setTextColor(p.textDim, p.bg); canvas.drawString(ss, hal::display::width() / 2, 175);
    canvas.setTextSize(1);                                     canvas.drawString(dl, hal::display::width() / 2, 200);
    canvas.setTextDatum(TL_DATUM);
    return;
  }

  // Landscape: 240×135 direct-to-LCD. Full fill only on entry; after that
  // text glyph bg cells repaint themselves and the pet box (small, ~90×50)
  // gets a fillRect each pet tick — small enough not to tear.
  hal::display::setRotation(orient);
  bool repaint = paintedOrient != orient;
  if (repaint) { hal::display::lcd().fillScreen(p.bg); paintedOrient = orient; lastSec = 0xFF; }

  // Seconds tick at 1Hz; redrawing 3 strings at 60fps is 180 SPI ops/sec
  // for nothing. Gate on the second changing (or full repaint).
  if (repaint || t.s != lastSec) {
    lastSec = t.s;
    char wdl[12]; snprintf(wdl, sizeof(wdl), "%s %s %02u", DOW[dow(d)], MON[mi], d.day);
    char ssl[3]; snprintf(ssl, sizeof(ssl), "%02u", t.s);
    hal::display::lcd().setTextDatum(MC_DATUM);
    hal::display::lcd().setTextSize(3); hal::display::lcd().setTextColor(p.text, p.bg);    hal::display::lcd().drawString(hm, 170, 42);
    hal::display::lcd().setTextSize(2); hal::display::lcd().setTextColor(p.textDim, p.bg); hal::display::lcd().drawString(ssl, 170, 72);
                                                                                           hal::display::lcd().drawString(wdl, 170, 102);
    hal::display::lcd().setTextDatum(TL_DATUM);
    hal::display::lcd().setTextSize(1);
  }

  // Pet on left at 5 fps. Clear includes the overlay-particle zone above
  // the body (y<30) — species draw Zzz/hearts there via BUDDY_Y_OVERLAY=6
  // which doesn't go through _yb, so the box has to cover it.
  static uint32_t lastPetTick = 0;
  if (millis() - lastPetTick >= 200) {
    lastPetTick = millis();
    if (buddyMode) {
      // ASCII glyphs don't self-clear; wipe the box each tick. Species
      // hardcode BUDDY_X_CENTER=67 / BUDDY_Y_OVERLAY=6 for particles so
      // keep portrait coords and just swap the surface — pet lands
      // upper-left of landscape, which is where we want it anyway.
      hal::display::lcd().fillRect(0, 0, 115, 90, p.bg);
      buddyRenderTo(&hal::display::lcd(), activeState);
    } else {
      // Full-frame GIFs paint every pixel (transparent → pal.bg), so a
      // per-tick clear just adds a visible black flash between wipe and
      // last scanline. The entry fillScreen on paintedOrient change
      // already covers the surround.
      characterSetState(activeState);
      characterRenderTo(&hal::display::lcd(), 57, 45);
    }
  }
  hal::display::setRotation(0);
}

}}
