#include "hud.h"
#include "../hal/display.h"
#include "../character.h"
#include "../data.h"
#include "../stats.h"
#include <stdio.h>
#include <cstring>

extern M5GFX& canvas;
extern TamaState tama;

namespace screen { namespace hud {

static uint8_t  msgScroll   = 0;
static uint32_t lastLineGen = 0;

// Helper to wrap text into fixed-width columns
static uint8_t wrapInto(const char* in, char out[][24], uint8_t maxRows, uint8_t width) {
  uint8_t row = 0, col = 0;
  const char* p = in;
  while (*p && row < maxRows) {
    while (*p == ' ') p++;                     // skip leading spaces
    // measure next word
    const char* w = p;
    while (*p && *p != ' ') p++;
    uint8_t wlen = p - w;
    if (wlen == 0) break;
    uint8_t need = (col > 0 ? 1 : 0) + wlen;
    if (col + need > width) {
      out[row][col] = 0;
      if (++row >= maxRows) return row;
      out[row][0] = ' '; col = 1;              // continuation indent
    }
    if (col > 1 || (col == 1 && out[row][0] != ' ')) out[row][col++] = ' ';
    else if (col == 1 && row > 0) {}           // already have the indent space
    // hard-break words that still don't fit
    while (wlen > width - col) {
      uint8_t take = width - col;
      memcpy(&out[row][col], w, take); col += take; w += take; wlen -= take;
      out[row][col] = 0;
      if (++row >= maxRows) return row;
      out[row][0] = ' '; col = 1;
    }
    memcpy(&out[row][col], w, wlen); col += wlen;
  }
  if (col > 0 && row < maxRows) { out[row][col] = 0; row++; }
  return row;
}

void draw() {
  const Palette& p = characterPalette();
  const int SHOW = 3;
  const int LH = hal::display::isLarge() ? 16 : 8;
  const int WIDTH = hal::display::isLarge() ? 13 : 21;
  const int AREA = SHOW * LH + 4;
  int W = hal::display::width();
  int H = hal::display::height();

  canvas.fillRect(0, H - AREA, W, AREA, p.bg);
  canvas.setTextSize(hal::display::isLarge() ? 2 : 1);

  if (tama.lineGen != lastLineGen) { msgScroll = 0; lastLineGen = tama.lineGen; }
  // NOTE: wake() call removed; this notification was informational only.
  // It will be triggered by the main loop's button/BLE handlers anyway.

  if (tama.nLines == 0) {
    canvas.setTextColor(p.text, p.bg);
    canvas.setCursor(4, H - LH - 2);
    canvas.print(tama.msg);
    return;
  }

  // Wrap all transcript lines into a flat display buffer. Track which
  // transcript index each display row came from, so we can dim older ones.
  static char disp[32][24];
  static uint8_t srcOf[32];
  uint8_t nDisp = 0;
  for (uint8_t i = 0; i < tama.nLines && nDisp < 32; i++) {
    uint8_t got = wrapInto(tama.lines[i], &disp[nDisp], 32 - nDisp, WIDTH);
    for (uint8_t j = 0; j < got; j++) srcOf[nDisp + j] = i;
    nDisp += got;
  }

  uint8_t maxBack = (nDisp > SHOW) ? (nDisp - SHOW) : 0;
  if (msgScroll > maxBack) msgScroll = maxBack;

  int end = (int)nDisp - msgScroll;
  int start = end - SHOW; if (start < 0) start = 0;
  uint8_t newest = tama.nLines - 1;
  for (int i = 0; start + i < end; i++) {
    uint8_t row = start + i;
    bool fresh = (srcOf[row] == newest) && (msgScroll == 0);
    canvas.setTextColor(fresh ? p.text : p.textDim, p.bg);
    canvas.setCursor(4, H - AREA + 2 + i * LH);
    canvas.print(disp[row]);
  }
  if (msgScroll > 0) {
    canvas.setTextColor(p.body, p.bg);
    canvas.setCursor(W - 18, H - LH - 2);
    canvas.printf("-%u", msgScroll);
  }
}

void scrollMessage() {
  msgScroll = (msgScroll >= 30) ? 0 : msgScroll + 1;
}

}}
