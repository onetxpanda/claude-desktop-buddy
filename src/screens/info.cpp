#include "info.h"
#include "../hal/display.h"
#include "../hal/power.h"
#include "../character.h"
#include "../ble_bridge.h"
#include "../data.h"
#include "../stats.h"
#include <stdio.h>
#include <stdarg.h>

// Declared in main.cpp
extern M5GFX& canvas;
extern const char* stateNames[];
extern TamaState tama;
extern char btName[16];
extern uint8_t brightLevel;
extern int activeState;  // PersonaState enum, but int to avoid including the enum definition

namespace screen { namespace info {

static int W = 135;
static int H = 240;
static constexpr uint8_t INFO_PAGES = 6;
static constexpr uint16_t HOT = 0xFA20;   // red-orange: warnings, impatience, deny

// Section title for each page — drawn big at the top of the page so the
// content's purpose reads at a glance. Order matches the infoPage indices.
static const char* const SECTION_NAMES[INFO_PAGES] = {
  "About", "Buttons", "Claude", "Device", "Bluetooth", "Credits"
};

static uint8_t infoPage = 0;

void draw() {
  W = hal::display::width();
  H = hal::display::height();
  const Palette& p = characterPalette();
  const bool lg = hal::display::isLarge();

  // Reclaim the full screen — main.cpp now skips the buddy render when
  // displayMode == DISP_INFO so we don't have to leave a peek band on top.
  canvas.fillRect(0, 0, W, H, p.bg);

  // Sizing knobs:
  //   titleSz  = section header (e.g. "Bluetooth") — biggest thing on screen
  //   bodySz   = body text — size 2 on Core2, size 1 on StickC
  //   bigSz    = ad-hoc emphasis (battery %, BT status word) — title-level
  const int titleSz = lg ? 3 : 2;
  const int bodySz  = lg ? 2 : 1;
  const int bigSz   = lg ? 4 : 2;
  const int LH      = 8 * bodySz;            // body line height
  const int titleH  = 8 * titleSz;
  const int pad     = lg ? 6 : 4;

  // ── Header band ──
  canvas.setTextColor(p.body, p.bg);
  canvas.setTextSize(titleSz);
  canvas.setCursor(pad, pad);
  canvas.print(SECTION_NAMES[infoPage]);

  canvas.setTextSize(bodySz);
  canvas.setTextColor(p.textDim, p.bg);
  char pageStr[12];
  snprintf(pageStr, sizeof(pageStr), "%u of %u", infoPage + 1, INFO_PAGES);
  int pageStrW = (int)strlen(pageStr) * 6 * bodySz;
  // Baseline-align with the title's bottom edge for visual harmony.
  canvas.setCursor(W - pageStrW - pad, pad + titleH - 8 * bodySz);
  canvas.print(pageStr);

  canvas.drawFastHLine(pad, pad + titleH + 4, W - 2 * pad, p.textDim);

  // ── Body ──
  // Body wraps into a second column on Core2 only when bodySz=1 — at
  // bodySz=2 each column would only be 160px ≈ 12 chars, narrower than
  // most existing lines (19-22 chars), so columns would overlap.
  int y = pad + titleH + 10 + (lg ? 4 : 0);
  const int yTop = y;
  int colX = pad;
  auto wrap = [&](int needed) {
    if (lg && bodySz == 1 && colX == pad && y + needed > H - pad) {
      colX = W / 2 + pad;
      y = yTop;
    }
  };
  auto gap = [&](int px) { y += px; wrap(LH); };
  auto ln = [&](const char* fmt, ...) {
    char b[64]; va_list a; va_start(a, fmt); vsnprintf(b, sizeof(b), fmt, a); va_end(a);
    wrap(LH);
    canvas.setCursor(colX, y); canvas.print(b); y += LH;
  };

  canvas.setTextSize(bodySz);

  if (infoPage == 0) {
    canvas.setTextColor(p.textDim, p.bg);
    ln("I watch your Claude");
    ln("desktop sessions.");
    gap(LH / 2);
    ln("I sleep when idle,");
    ln("wake when you work,");
    ln("get impatient when");
    ln("approvals pile up.");
    gap(LH / 2);
    canvas.setTextColor(p.text, p.bg);
    ln("Press A on a prompt");
    ln("to approve from here.");
    gap(LH / 2);
    canvas.setTextColor(p.textDim, p.bg);
    ln("18 species. Settings");
    ln("> ascii pet to cycle.");

  } else if (infoPage == 1) {
    canvas.setTextColor(p.text, p.bg);    ln("A   front");
    canvas.setTextColor(p.textDim, p.bg); ln("    next screen");
    ln("    approve prompt"); gap(LH / 4);
    canvas.setTextColor(p.text, p.bg);    ln("B   right side");
    canvas.setTextColor(p.textDim, p.bg); ln("    next page");
    ln("    deny prompt"); gap(LH / 4);
    canvas.setTextColor(p.text, p.bg);    ln("hold A");
    canvas.setTextColor(p.textDim, p.bg); ln("    menu"); gap(LH / 4);
    canvas.setTextColor(p.text, p.bg);    ln("Power  left side");
    canvas.setTextColor(p.textDim, p.bg); ln("    tap = screen off");
    ln("    hold 6s = off");

  } else if (infoPage == 2) {
    canvas.setTextColor(p.body, p.bg);
    ln("CLAUDE");
    canvas.setTextColor(p.textDim, p.bg);
    ln("  sessions  %u", tama.sessionsTotal);
    ln("  running   %u", tama.sessionsRunning);
    ln("  waiting   %u", tama.sessionsWaiting);
    gap(LH / 2);
    canvas.setTextColor(p.body, p.bg);
    ln("LINK");
    canvas.setTextColor(p.textDim, p.bg);
    ln("  via       %s", dataScenarioName());
    ln("  ble       %s", !bleConnected() ? "-" : bleSecure() ? "encrypted" : "OPEN");
    uint32_t age = (millis() - tama.lastUpdated) / 1000;
    ln("  last msg  %lus", (unsigned long)age);
    ln("  state     %s", stateNames[activeState]);

  } else if (infoPage == 3) {
    int vBat_mV = (int)(hal::power::batVoltage() * 1000);
    int iBat_mA = (int)hal::power::batCurrent();
    int vBus_mV = (int)(hal::power::busVoltage() * 1000);
    int pct = (vBat_mV - 3200) / 10;
    if (pct < 0) pct = 0; if (pct > 100) pct = 100;
    bool usb      = vBus_mV > 4000;
    bool charging = usb && iBat_mA > 1;
    bool full     = usb && vBat_mV > 4100 && iBat_mA < 10;

    // Battery % sits big in the upper-left of the body region; status word
    // hangs to its right at body size, baseline-aligned to the big number.
    canvas.setTextColor(p.text, p.bg);
    canvas.setTextSize(bigSz);
    canvas.setCursor(colX, y);
    canvas.printf("%d%%", pct);
    canvas.setTextSize(bodySz);
    canvas.setTextColor(full ? GREEN : (charging ? HOT : p.textDim), p.bg);
    int bigW = 6 * bigSz * 4;   // up to "100%" = 4 chars
    canvas.setCursor(colX + bigW + 4, y + 8 * bigSz - 8 * bodySz);
    canvas.print(full ? "full" : (charging ? "charging" : (usb ? "usb" : "battery")));
    y += 8 * bigSz + (lg ? 6 : 4);

    canvas.setTextColor(p.textDim, p.bg);
    ln("battery   %d.%02dV", vBat_mV/1000, (vBat_mV%1000)/10);
    ln("current   %+dmA",   iBat_mA);
    if (usb) ln("usb in    %d.%02dV", vBus_mV/1000, (vBus_mV%1000)/10);
    gap(LH / 2);

    canvas.setTextColor(p.body, p.bg);
    ln("SYSTEM");
    canvas.setTextColor(p.textDim, p.bg);
    if (ownerName()[0]) ln("  owner    %s", ownerName());
    uint32_t up = millis() / 1000;
    ln("  uptime   %luh %02lum", up / 3600, (up / 60) % 60);
    ln("  heap     %uKB", ESP.getFreeHeap() / 1024);
    ln("  bright   %u/4", brightLevel);
    ln("  bt       %s", settings().bt ? (dataBtActive() ? "linked" : "on") : "off");

  } else if (infoPage == 4) {
    bool linked = settings().bt && dataBtActive();
    const bool inPairing = blePasskey() != 0;

    // Status word at title-size, contextually colored:
    //   green  = paired and live
    //   hot    = visible & advertising (waiting for desktop)
    //   dim    = bluetooth turned off in settings
    canvas.setTextColor(linked ? GREEN : (settings().bt ? HOT : p.textDim), p.bg);
    canvas.setTextSize(bigSz);
    canvas.setCursor(colX, y);
    canvas.print(linked ? "linked" : (settings().bt ? (inPairing ? "pairing" : "discover") : "off"));
    canvas.setTextSize(bodySz);
    y += 8 * bigSz + (lg ? 6 : 4);

    canvas.setTextColor(p.text, p.bg);
    ln("name");
    canvas.setTextColor(p.textDim, p.bg);
    ln(" %s", btName);
    canvas.setTextColor(p.text, p.bg);
    ln("mac");
    canvas.setTextColor(p.textDim, p.bg);
    uint8_t mac[6] = {0};
    esp_read_mac(mac, ESP_MAC_BT);
    // MAC on its own line — at size 2 the full 17-char form is 204px, plus
    // a label would overflow the right edge.
    ln(" %02X:%02X:%02X:%02X:%02X:%02X",
       mac[0],mac[1],mac[2],mac[3],mac[4],mac[5]);
    gap(LH / 2);

    if (linked) {
      uint32_t age = (millis() - tama.lastUpdated) / 1000;
      ln("last msg  %lus", (unsigned long)age);
    } else if (settings().bt) {
      canvas.setTextColor(p.body, p.bg);
      ln("TO PAIR");
      canvas.setTextColor(p.textDim, p.bg);
      ln(" Open Claude desktop");
      ln(" > Developer");
      ln(" > Hardware Buddy");
      gap(LH / 4);
      ln(" auto-connects");
    }

  } else {
    canvas.setTextColor(p.textDim, p.bg);
    ln("made by");
    canvas.setTextColor(p.text, p.bg);
    ln("Felix Rieseberg");
    gap(LH / 2);
    canvas.setTextColor(p.textDim, p.bg);
    ln("source");
    canvas.setTextColor(p.text, p.bg);
    ln("github.com/anthropics");
    ln("/claude-desktop-buddy");
    gap(LH / 2);
    canvas.setTextColor(p.textDim, p.bg);
    ln("hardware");
    canvas.setTextColor(p.text, p.bg);
    ln(lg ? "M5Stack Core2" : "M5StickC Plus");
    canvas.setTextColor(p.textDim, p.bg);
    ln("ESP32 + AXP192");
  }
}

void nextPage() {
  infoPage = (infoPage + 1) % INFO_PAGES;
}

uint8_t currentPage() {
  return infoPage;
}

}}
