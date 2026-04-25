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
}

void draw() {
  W = hal::display::width();
  H = hal::display::height();
  const Palette& p = characterPalette();
  const bool lg = hal::display::isLarge();
  // Single scale knob: size-1 on StickC, size-2 on Core2. Every literal
  // dimension below multiplies by S so all six pages reflow together.
  const int S = lg ? 2 : 1;
  const int LH = 8 * S;        // body line height
  const int HH = 12 * S;       // header line height
  const int TOP = lg ? 100 : 70;
  canvas.fillRect(0, TOP, W, H - TOP, p.bg);
  canvas.setTextSize(S);
  int y = TOP + 2;
  auto ln = [&](const char* fmt, ...) {
    char b[40]; va_list a; va_start(a, fmt); vsnprintf(b, sizeof(b), fmt, a); va_end(a);
    canvas.setCursor(4, y); canvas.print(b); y += LH;
  };

  if (infoPage == 0) {
    _infoHeader(p, y, "ABOUT", infoPage);
    canvas.setTextColor(p.textDim, p.bg);
    ln("I watch your Claude");
    ln("desktop sessions.");
    y += 6 * S;
    ln("I sleep when nothing's");
    ln("happening, wake when");
    ln("you start working,");
    ln("get impatient when");
    ln("approvals pile up.");
    y += 6 * S;
    canvas.setTextColor(p.text, p.bg);
    ln("Press A on a prompt");
    ln("to approve from here.");
    y += 6 * S;
    canvas.setTextColor(p.textDim, p.bg);
    ln("18 species. Settings");
    ln("> ascii pet to cycle.");

  } else if (infoPage == 1) {
    _infoHeader(p, y, "BUTTONS", infoPage);
    canvas.setTextColor(p.text, p.bg);    ln("A   front");
    canvas.setTextColor(p.textDim, p.bg); ln("    next screen");
    ln("    approve prompt"); y += 4 * S;
    canvas.setTextColor(p.text, p.bg);    ln("B   right side");
    canvas.setTextColor(p.textDim, p.bg); ln("    next page");
    ln("    deny prompt"); y += 4 * S;
    canvas.setTextColor(p.text, p.bg);    ln("hold A");
    canvas.setTextColor(p.textDim, p.bg); ln("    menu"); y += 4 * S;
    canvas.setTextColor(p.text, p.bg);    ln("Power  left side");
    canvas.setTextColor(p.textDim, p.bg); ln("    tap = screen off");
    ln("    hold 6s = off");

  } else if (infoPage == 2) {
    _infoHeader(p, y, "CLAUDE", infoPage);
    canvas.setTextColor(p.textDim, p.bg);
    ln("  sessions  %u", tama.sessionsTotal);
    ln("  running   %u", tama.sessionsRunning);
    ln("  waiting   %u", tama.sessionsWaiting);
    y += 8 * S;
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
    y += 20 * S;

    canvas.setTextColor(p.textDim, p.bg);
    ln("  battery  %d.%02dV", vBat_mV/1000, (vBat_mV%1000)/10);
    ln("  current  %+dmA", iBat_mA);
    if (usb) ln("  usb in   %d.%02dV", vBus_mV/1000, (vBus_mV%1000)/10);
    y += 8 * S;

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
    y += 20 * S;

    canvas.setTextColor(p.textDim, p.bg);
    canvas.setTextColor(p.text, p.bg);
    ln("  %s", btName);
    canvas.setTextColor(p.textDim, p.bg);
    uint8_t mac[6] = {0};
    esp_read_mac(mac, ESP_MAC_BT);
    ln("  %02X:%02X:%02X:%02X:%02X:%02X",
       mac[0],mac[1],mac[2],mac[3],mac[4],mac[5]);
    y += 8 * S;

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
      y += 4 * S;
      ln(" auto-connects via BLE");
    }

  } else {
    _infoHeader(p, y, "CREDITS", infoPage);
    canvas.setTextColor(p.textDim, p.bg);
    ln("made by");
    y += 4 * S;
    canvas.setTextColor(p.text, p.bg);
    ln("Felix Rieseberg");
    y += 12 * S;
    canvas.setTextColor(p.textDim, p.bg);
    ln("source");
    y += 4 * S;
    canvas.setTextColor(p.text, p.bg);
    ln("github.com/anthropics");
    ln("/claude-desktop-buddy");
    y += 12 * S;
    canvas.setTextColor(p.textDim, p.bg);
    ln("hardware");
    y += 4 * S;
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
