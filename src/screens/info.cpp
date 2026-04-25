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
extern M5Canvas& canvas;
extern const char* stateNames[];
extern TamaState tama;
extern char btName[16];
extern uint8_t brightLevel;
extern int activeState;  // PersonaState enum, but int to avoid including the enum definition

namespace screen { namespace info {

// W and H are read at runtime so Core2 (320×240) gets the correct values.
static int W = 135;
static int H = 240;
static constexpr uint8_t INFO_PAGES = 6;
static constexpr uint16_t HOT = 0xFA20;   // red-orange: warnings, impatience, deny

static uint8_t infoPage = 0;

static void _infoHeader(const Palette& p, int& y, const char* section, uint8_t page) {
  const int S = hal::display::isLarge() ? 2 : 1;
  canvas.setTextSize(S);
  canvas.setTextColor(p.text, p.bg);
  canvas.setCursor(4, y); canvas.print("Info");
  canvas.setTextColor(p.textDim, p.bg);
  // "n/N" is 3 chars wide; back off 6px per char per scale unit.
  canvas.setCursor(W - 18 * S - 4, y); canvas.printf("%u/%u", page + 1, INFO_PAGES);
  y += 12 * S;
  canvas.setTextColor(p.body, p.bg);
  canvas.setCursor(4, y); canvas.print(section);
  y += 12 * S;
  // Restore size 1 for the body — without this Core2 inherits the size-2
  // header setting and body lines at LH=8 overlap each other.
  canvas.setTextSize(1);
}

void draw() {
  W = hal::display::width();
  H = hal::display::height();
  const Palette& p = characterPalette();
  const bool lg = hal::display::isLarge();
  // Body stays at size 1 — the existing copy was written for ~22-char lines,
  // which at size 2 would either overflow Core2's 240px height or, in a
  // 2-column split, exceed each column's width. Header gets size 2 on Core2
  // for visual hierarchy.
  const int S = 1;
  const int LH = 8;
  const int TOP = lg ? 100 : 70;
  canvas.fillRect(0, TOP, W, H - TOP, p.bg);
  canvas.setTextSize(S);
  int y = TOP + 2;
  // On Core2, body wraps to a second column once it'd hit the bottom — at
  // size-1 body each column is W/2 ≈ 160px = 26 chars, comfortably wider
  // than the longest line in the existing copy.
  int colX = 4;
  const int colYStart = TOP + 2 + 2 * 12 * (lg ? 2 : 1);  // below 2 header rows
  auto wrap = [&](int needed) {
    if (lg && colX == 4 && y + needed > H - 2) {
      colX = W / 2 + 4;
      y = colYStart;
    }
  };
  auto gap = [&](int px) { y += px; wrap(LH); };
  auto ln = [&](const char* fmt, ...) {
    char b[40]; va_list a; va_start(a, fmt); vsnprintf(b, sizeof(b), fmt, a); va_end(a);
    wrap(LH);
    canvas.setCursor(colX, y); canvas.print(b); y += LH;
  };

  if (infoPage == 0) {
    _infoHeader(p, y, "ABOUT", infoPage);
    canvas.setTextColor(p.textDim, p.bg);
    ln("I watch your Claude");
    ln("desktop sessions.");
    gap(6 * S);
    ln("I sleep when nothing's");
    ln("happening, wake when");
    ln("you start working,");
    ln("get impatient when");
    ln("approvals pile up.");
    gap(6 * S);
    canvas.setTextColor(p.text, p.bg);
    ln("Press A on a prompt");
    ln("to approve from here.");
    gap(6 * S);
    canvas.setTextColor(p.textDim, p.bg);
    ln("18 species. Settings");
    ln("> ascii pet to cycle.");

  } else if (infoPage == 1) {
    _infoHeader(p, y, "BUTTONS", infoPage);
    canvas.setTextColor(p.text, p.bg);    ln("A   front");
    canvas.setTextColor(p.textDim, p.bg); ln("    next screen");
    ln("    approve prompt"); gap(4 * S);
    canvas.setTextColor(p.text, p.bg);    ln("B   right side");
    canvas.setTextColor(p.textDim, p.bg); ln("    next page");
    ln("    deny prompt"); gap(4 * S);
    canvas.setTextColor(p.text, p.bg);    ln("hold A");
    canvas.setTextColor(p.textDim, p.bg); ln("    menu"); gap(4 * S);
    canvas.setTextColor(p.text, p.bg);    ln("Power  left side");
    canvas.setTextColor(p.textDim, p.bg); ln("    tap = screen off");
    ln("    hold 6s = off");

  } else if (infoPage == 2) {
    _infoHeader(p, y, "CLAUDE", infoPage);
    canvas.setTextColor(p.textDim, p.bg);
    ln("  sessions  %u", tama.sessionsTotal);
    ln("  running   %u", tama.sessionsRunning);
    ln("  waiting   %u", tama.sessionsWaiting);
    gap(8 * S);
    canvas.setTextColor(p.text, p.bg);
    ln("LINK");
    canvas.setTextColor(p.textDim, p.bg);
    ln("  via       %s", dataScenarioName());
    ln("  ble       %s", !bleConnected() ? "-" : bleSecure() ? "encrypted" : "OPEN");
    uint32_t age = (millis() - tama.lastUpdated) / 1000;
    ln("  last msg  %lus", (unsigned long)age);
    ln("  state     %s", stateNames[activeState]);

  } else if (infoPage == 3) {
    _infoHeader(p, y, "DEVICE", infoPage);

    int vBat_mV = (int)(hal::power::batVoltage() * 1000);
    int iBat_mA = (int)hal::power::batCurrent();
    int vBus_mV = (int)(hal::power::busVoltage() * 1000);
    int pct = (vBat_mV - 3200) / 10;   // (v-3.2)/(4.2-3.2)*100 = (v-3.2)*100 = (mv-3200)/10
    if (pct < 0) pct = 0; if (pct > 100) pct = 100;
    bool usb = vBus_mV > 4000;
    bool charging = usb && iBat_mA > 1;
    bool full = usb && vBat_mV > 4100 && iBat_mA < 10;

    canvas.setTextColor(p.text, p.bg);
    canvas.setTextSize(2 * S);
    canvas.setCursor(4, y);
    canvas.printf("%d%%", pct);
    canvas.setTextSize(S);
    canvas.setTextColor(full ? GREEN : (charging ? HOT : p.textDim), p.bg);
    canvas.setCursor(64 * S, y + 4 * S);
    canvas.print(full ? "full" : (charging ? "charging" : (usb ? "usb" : "battery")));
    gap(20 * S);

    canvas.setTextColor(p.textDim, p.bg);
    ln("  battery  %d.%02dV", vBat_mV/1000, (vBat_mV%1000)/10);
    ln("  current  %+dmA", iBat_mA);
    if (usb) ln("  usb in   %d.%02dV", vBus_mV/1000, (vBus_mV%1000)/10);
    gap(8 * S);

    canvas.setTextColor(p.text, p.bg);
    ln("SYSTEM");
    canvas.setTextColor(p.textDim, p.bg);
    if (ownerName()[0]) ln("  owner    %s", ownerName());
    uint32_t up = millis() / 1000;
    ln("  uptime   %luh %02lum", up / 3600, (up / 60) % 60);
    ln("  heap     %uKB", ESP.getFreeHeap() / 1024);
    ln("  bright   %u/4", brightLevel);
    ln("  bt       %s", settings().bt ? (dataBtActive() ? "linked" : "on") : "off");

  } else if (infoPage == 4) {
    _infoHeader(p, y, "BLUETOOTH", infoPage);
    bool linked = settings().bt && dataBtActive();

    canvas.setTextColor(linked ? GREEN : (settings().bt ? HOT : p.textDim), p.bg);
    canvas.setTextSize(2 * S);
    canvas.setCursor(4, y);
    canvas.print(linked ? "linked" : (settings().bt ? "discover" : "off"));
    canvas.setTextSize(S);
    gap(20 * S);

    canvas.setTextColor(p.textDim, p.bg);
    canvas.setTextColor(p.text, p.bg);
    ln("  %s", btName);
    canvas.setTextColor(p.textDim, p.bg);
    uint8_t mac[6] = {0};
    esp_read_mac(mac, ESP_MAC_BT);
    ln("  %02X:%02X:%02X:%02X:%02X:%02X",
       mac[0],mac[1],mac[2],mac[3],mac[4],mac[5]);
    gap(8 * S);

    if (linked) {
      uint32_t age = (millis() - tama.lastUpdated) / 1000;
      ln("  last msg  %lus", (unsigned long)age);
    } else if (settings().bt) {
      canvas.setTextColor(p.text, p.bg);
      ln("TO PAIR");
      canvas.setTextColor(p.textDim, p.bg);
      ln(" Open Claude desktop");
      ln(" > Developer");
      ln(" > Hardware Buddy");
      gap(4 * S);
      ln(" auto-connects via BLE");
    }

  } else {
    _infoHeader(p, y, "CREDITS", infoPage);
    canvas.setTextColor(p.textDim, p.bg);
    ln("made by");
    gap(4 * S);
    canvas.setTextColor(p.text, p.bg);
    ln("Felix Rieseberg");
    gap(12 * S);
    canvas.setTextColor(p.textDim, p.bg);
    ln("source");
    gap(4 * S);
    canvas.setTextColor(p.text, p.bg);
    ln("github.com/anthropics");
    ln("/claude-desktop-buddy");
    gap(12 * S);
    canvas.setTextColor(p.textDim, p.bg);
    ln("hardware");
    gap(4 * S);
    ln("M5StickC Plus");
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
