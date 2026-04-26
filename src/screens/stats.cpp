#include "stats.h"
#include "../hal/display.h"
#include "../character.h"
#include "../stats.h"     // project data stats (different dir)
#include "../data.h"
#include <stdio.h>
#include <string.h>

extern M5GFX& canvas;
extern TamaState tama;
extern void applyDisplayMode();          // defined in main.cpp
extern void beep(uint16_t freq, uint16_t dur);  // defined in main.cpp

static constexpr uint16_t HOT = 0xFA20;   // red-orange: warnings, impatience, deny

namespace screen { namespace petstats {

static constexpr uint8_t PET_PAGES = 2;
static uint8_t petPage = 0;

static uint8_t currentPage() { return petPage; }
void    nextPage()    { petPage = (petPage + 1) % PET_PAGES; }

bool handleButton(Btn b, BtnEvent e) {
  if (b == Btn::B && e == BtnEvent::Tap) {
    beep(2400, 30);
    nextPage();
    applyDisplayMode();
    return true;
  }
  return false;
}

static void tinyHeart(int x, int y, bool filled, uint16_t col) {
  const int r = hal::display::isLarge() ? 6 : 4;
  if (filled) {
    canvas.fillCircle(x - r, y, r, col);
    canvas.fillCircle(x + r, y, r, col);
    canvas.fillTriangle(x - 2*r, y + r/2, x + 2*r, y + r/2, x, y + 2*r + r/2, col);
  } else {
    canvas.drawCircle(x - r, y, r, col);
    canvas.drawCircle(x + r, y, r, col);
    canvas.drawLine(x - 2*r, y + r/2, x, y + 2*r + r/2, col);
    canvas.drawLine(x + 2*r, y + r/2, x, y + 2*r + r/2, col);
  }
}

static void drawPetStats(const Palette& p) {
  const int W = hal::display::width();
  const int H = hal::display::height();
  const bool lg = hal::display::isLarge();
  // peekTop() in character.cpp returns 100 on Core2; matching TOP here keeps
  // the stats overlay from clipping the buddy's lower edge.
  const int TOP = lg ? 100 : 70;
  canvas.fillRect(0, TOP, W, H - TOP, p.bg);

  // Mood: 4 hearts centered in quarter-width cells
  uint8_t mood = statsMoodTier();
  uint16_t moodCol = (mood >= 3) ? RED : (mood >= 2) ? HOT : p.textDim;
  const int moodY = TOP + 16;
  for (int i = 0; i < 4; i++) {
    int cx = (W * (2 * i + 1)) / 8;
    tinyHeart(cx, moodY, i < mood, moodCol);
  }

  // Fed: 10 dots centered in tenth-width cells
  uint8_t fed = statsFedProgress();
  const int dotR = lg ? 5 : 4;
  const int dotsY = TOP + 38;
  for (int i = 0; i < 10; i++) {
    int cx = (W * (2 * i + 1)) / 20;
    if (i < fed) canvas.fillCircle(cx, dotsY, dotR, p.body);
    else         canvas.drawCircle(cx, dotsY, dotR, p.textDim);
  }

  // Energy: 5 bars centered in fifth-width cells
  uint8_t en = statsEnergyTier();
  uint16_t enCol = (en >= 4) ? 0x07FF : (en >= 2) ? 0xFFE0 : HOT;
  const int barW = lg ? 22 : 15;
  const int barH = lg ? 14 : 10;
  const int barsY = TOP + 52;
  for (int i = 0; i < 5; i++) {
    int cx = (W * (2 * i + 1)) / 10;
    if (i < en) canvas.fillRect(cx - barW/2, barsY, barW, barH, enCol);
    else        canvas.drawRect(cx - barW/2, barsY, barW, barH, p.textDim);
  }

  auto fmtTok = [](char* buf, size_t n, uint32_t v) {
    if      (v < 1000)        snprintf(buf, n, "%lu", v);
    else if (v < 100000)      snprintf(buf, n, "%lu.%luK", v/1000, (v/100)%10);
    else if (v < 1000000)     snprintf(buf, n, "%luK", v/1000);
    else if (v < 100000000)   snprintf(buf, n, "%lu.%luM", v/1000000, (v/100000)%10);
    else if (v < 1000000000)  snprintf(buf, n, "%luM", v/1000000);
    else                      snprintf(buf, n, "%lu.%luB", v/1000000000, (v/100000000)%10);
  };
  char aprBuf[8], dnyBuf[8], tokBuf[12], tdyBuf[12], napBuf[8];
  snprintf(aprBuf, sizeof(aprBuf), "%u", stats().approvals);
  snprintf(dnyBuf, sizeof(dnyBuf), "%u", stats().denials);
  fmtTok(tokBuf, sizeof(tokBuf), stats().tokens);
  fmtTok(tdyBuf, sizeof(tdyBuf), tama.tokensToday);
  uint32_t nap = stats().napSeconds;
  if (nap >= 3600) snprintf(napBuf, sizeof(napBuf), "%luh", nap/3600);
  else             snprintf(napBuf, sizeof(napBuf), "%lum", nap/60);

  if (lg) {
    // Core2: single row of 5 across the wider canvas. Values at size 3,
    // labels at size 2 — actually fills the screen instead of huddling
    // five tiny cells in the StickC's portrait grid.
    const int statY  = TOP + 70;
    const int valSz  = 3;
    const int lblSz  = 2;
    const int lblOff = 8 * valSz + 4;   // value baseline + small gap
    const char* L[5] = { "APR", "DNY", "TOK", "TDY", "NAP" };
    const char* V[5] = { aprBuf, dnyBuf, tokBuf, tdyBuf, napBuf };
    for (int i = 0; i < 5; i++) {
      int cx = (W * (2 * i + 1)) / 10;
      canvas.setTextSize(valSz);
      canvas.setTextColor(p.text, p.bg);
      // Center: char width at size N is 6*N px, so half-width is strlen*6*N/2
      canvas.setCursor(cx - ((int)strlen(V[i]) * 6 * valSz) / 2, statY);
      canvas.print(V[i]);
      canvas.setTextSize(lblSz);
      canvas.setTextColor(p.textDim, p.bg);
      canvas.setCursor(cx - ((int)strlen(L[i]) * 6 * lblSz) / 2, statY + lblOff);
      canvas.print(L[i]);
    }
  } else {
    // StickC portrait: 2 rows × 2 cells + centered TOK. Original layout.
    int y = TOP + 66;
    const char* labels[2][2] = { {"APR","DNY"}, {"TDY","NAP"} };
    const char* values[2][2] = {
      { aprBuf, dnyBuf },
      { tdyBuf, napBuf },
    };
    const int colCenterX[2] = { W / 4, (3 * W) / 4 };
    for (int r = 0; r < 2; r++) {
      int ry = y + r * 34;
      for (int c = 0; c < 2; c++) {
        canvas.setTextSize(2);
        canvas.setTextColor(p.text, p.bg);
        // strlen × char-width-at-size-2 (12px) / 2 to center
        canvas.setCursor(colCenterX[c] - (int)strlen(values[r][c]) * 6, ry);
        canvas.print(values[r][c]);
        canvas.setTextColor(p.textDim, p.bg);
        canvas.setCursor(colCenterX[c] - (int)strlen(labels[r][c]) * 6, ry + 18);
        canvas.print(labels[r][c]);
      }
    }

    int ry = y + 2 * 34;
    canvas.setTextSize(2);
    canvas.setTextColor(p.text, p.bg);
    canvas.setCursor(W / 2 - (int)strlen(tokBuf) * 6, ry);
    canvas.print(tokBuf);
    canvas.setTextColor(p.textDim, p.bg);
    canvas.setCursor(W / 2 - 18, ry + 18);
    canvas.print("TOK");
  }
}

static void drawPetHowTo(const Palette& p) {
  const int W = hal::display::width();
  const int H = hal::display::height();
  const int TOP = 70;
  canvas.fillRect(0, TOP, W, H - TOP, p.bg);
  canvas.setTextSize(1);
  int y = TOP + 2;
  auto ln = [&](uint16_t c, const char* s) {
    canvas.setTextColor(c, p.bg); canvas.setCursor(6, y); canvas.print(s); y += 9;
  };
  auto gap = [&]() { y += 4; };

  ln(p.body,    "MOOD");
  ln(p.textDim, " approve fast = up");
  ln(p.textDim, " deny lots = down"); gap();

  ln(p.body,    "FED");
  ln(p.textDim, " 50K tokens =");
  ln(p.textDim, " level up + confetti"); gap();

  ln(p.body,    "ENERGY");
  ln(p.textDim, " face-down to nap");
  ln(p.textDim, " refills to full"); gap();

  ln(p.textDim, "idle 30s = off");
  ln(p.textDim, "any button = wake"); gap();

  ln(p.textDim, "A: screens  B: page");
  ln(p.textDim, "hold A: menu");
}

void draw() {
  const Palette& p = characterPalette();
  if (petPage == 0) drawPetStats(p);
  else              drawPetHowTo(p);
}

}}
