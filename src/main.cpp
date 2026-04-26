#include <M5Unified.h>
#include <LittleFS.h>
#include <stdarg.h>
#include "ble_bridge.h"
#include "data.h"
#include "buddy.h"
#include "hal/beep.h"
#include "hal/rtc.h"
#include "hal/power.h"
#include "hal/imu.h"
#include "hal/buttons.h"
#include "hal/display.h"
#include "hal/hal.h"
#include "input.h"
#include "ota.h"
#include "version.h"

M5Canvas& canvas = hal::display::sprite();

// Advertise as "Claude-XXXX" (last two BT MAC bytes) so multiple sticks
// in one room are distinguishable in the desktop picker. Name persists in
// btName for the BLUETOOTH info page.
char btName[16] = "Claude";
static void startBt() {
  uint8_t mac[6] = {0};
  esp_read_mac(mac, ESP_MAC_BT);
  snprintf(btName, sizeof(btName), "Claude-%02X%02X", mac[4], mac[5]);
  bleInit(btName);
}

#include "character.h"
#include "screens/passkey.h"
#include "screens/info.h"
#include "screens/hud.h"
#include "screens/approval.h"
#include "screens/clock.h"
#include "screens/stats.h"
#include "screens/menu.h"
#include "screens/settings.h"
#include "screens/reset.h"
#include "stats.h"
const int W = 135, H = 240;
const int CX = W / 2;
const int CY_BASE = 120;
const int LED_PIN = 10;          // red LED, active-low

// Colors used across multiple UI surfaces
const uint16_t HOT   = 0xFA20;   // red-orange: warnings, impatience, deny
const uint16_t PANEL = 0x2104;   // overlay panel background

enum PersonaState { P_SLEEP, P_IDLE, P_BUSY, P_ATTENTION, P_CELEBRATE, P_DIZZY, P_HEART };
const char* stateNames[] = { "sleep", "idle", "busy", "attention", "celebrate", "dizzy", "heart" };

TamaState    tama;
PersonaState baseState   = P_SLEEP;
PersonaState activeState = P_SLEEP;
uint32_t     oneShotUntil = 0;
uint32_t     lastShakeCheck = 0;
float        accelBaseline = 1.0f;
unsigned long t = 0;

// Menu
bool    menuOpen    = false;
uint8_t brightLevel = 4;           // 0..4 → ScreenBreath 20..100

// Input event synthesizer state
struct BtnSynth {
  bool     prevA       = false;
  bool     prevB       = false;
  bool     aLongFired  = false;
};
static BtnSynth bs;

enum DisplayMode { DISP_NORMAL, DISP_PET, DISP_INFO, DISP_COUNT };
uint8_t displayMode = DISP_NORMAL;
char     lastPromptId[40] = "";
uint32_t lastInteractMs = 0;
bool     dimmed = false;
bool     screenOff = false;
bool     swallowBtnA = false;
bool     swallowBtnB = false;
bool     buddyMode = false;
bool     gifAvailable = false;
const uint8_t SPECIES_GIF = 0xFF;   // species NVS sentinel: use the installed GIF

// Cycle GIF (if installed) → ASCII species 0..N-1 → GIF. Persisted to the
// existing "species" NVS key; 0xFF means GIF mode.
static void nextPet() {
  uint8_t n = buddySpeciesCount();
  if (!buddyMode) {                          // GIF → species 0
    buddyMode = true;
    buddySetSpeciesIdx(0);
    speciesIdxSave(0);
  } else if (buddySpeciesIdx() + 1 >= n && gifAvailable) {  // last species → GIF
    buddyMode = false;
    speciesIdxSave(SPECIES_GIF);
  } else {                                   // species i → species i+1
    buddyNextSpecies();
  }
  characterInvalidate();
  if (buddyMode) buddyInvalidate();
}
uint32_t wakeTransitionUntil = 0;
const uint32_t SCREEN_OFF_MS = 30000;

bool     napping = false;
uint32_t napStartMs = 0;
uint32_t promptArrivedMs = 0;

// Face-down = Z-axis dominant and negative. Debounced so a toss doesn't count.
static bool isFaceDown() {
  float ax, ay, az;
  hal::imu::readAccel(ax, ay, az);
  return az < -0.7f && fabsf(ax) < 0.4f && fabsf(ay) < 0.4f;
}

static void applyBrightness() { hal::power::setBrightness(brightLevel); }

static void wake() {
  lastInteractMs = millis();
  if (screenOff) {
    hal::power::setLcdPower(true);
    applyBrightness();
    screenOff = false;
    wakeTransitionUntil = millis() + 12000;
  }
  if (dimmed) { applyBrightness(); dimmed = false; }
}
bool     responseSent = false;

void beep(uint16_t freq, uint16_t dur) {
  if (settings().sound) hal::beep::tone(freq, dur);
}

void sendCmd(const char* json) {
  Serial.println(json);
  size_t n = strlen(json);
  bleWrite((const uint8_t*)json, n);
  bleWrite((const uint8_t*)"\n", 1);
}

void applyDisplayMode() {
  bool peek = displayMode != DISP_NORMAL;
  characterSetPeek(peek);
  buddySetPeek(peek);
  // Clear the whole sprite on mode switch. drawInfo/drawPet clear their
  // own regions when they run, but when you switch FROM info/pet TO normal,
  // those functions stop running and their stale pixels stay behind. Full
  // clear is cheap and guarantees no leftovers between modes.
  canvas.fillSprite(0x0000);
  characterInvalidate();  // redraws character on next tick (text mode path)
}

bool    settingsOpen = false;
bool    resetOpen = false;

static void applySetting(uint8_t idx) {
  Settings& s = settings();
  switch (idx) {
    case 0:
      brightLevel = (brightLevel + 1) % 5;
      applyBrightness();
      return;
    case 1: s.sound = !s.sound; break;
    case 2:
      // BT toggle is a stored preference only — BLE stays live. Turning
      // BLE off cleanly would require tearing down the BLE stack which
      // the Arduino BLE library doesn't do reliably. If we need a
      // hard-off someday, stop advertising via BLEDevice::getAdvertising().
      s.bt = !s.bt;
      break;
    case 3: s.wifi = !s.wifi; break;   // stored only — no WiFi stack linked
    case 4: s.led = !s.led; break;
    case 5: s.hud = !s.hud; break;
    case 6: s.clockRot = (s.clockRot + 1) % 3; break;
    case 7: nextPet(); return;
    case 8: resetOpen = true; screen::reset::setSelected(0); screen::reset::setLastConfirm(0xFF, 0); return;
    case 9: settingsOpen = false; characterInvalidate(); return;
  }
  settingsSave();
}

// Tap-twice confirm: first tap arms (label flips to "really?"), second
// within 3s executes. Scrolling away clears the arm.
static void applyReset(uint8_t idx) {
  uint32_t now = millis();
  bool armed = (screen::reset::lastConfirmIdx() == idx) &&
               (int32_t)(now - screen::reset::confirmDeadline()) < 0;

  if (idx == 2) { resetOpen = false; return; }

  if (!armed) {
    screen::reset::setLastConfirm(idx, now + 3000);
    beep(1400, 60);
    return;
  }

  beep(800, 200);
  if (idx == 0) {
    // delete char: wipe /characters/, reboot into ASCII mode
    File d = LittleFS.open("/characters");
    if (d && d.isDirectory()) {
      File e;
      while ((e = d.openNextFile())) {
        char path[80];
        snprintf(path, sizeof(path), "/characters/%s", e.name());
        if (e.isDirectory()) {
          File f;
          while ((f = e.openNextFile())) {
            char fp[128];
            snprintf(fp, sizeof(fp), "%s/%s", path, f.name());
            f.close();
            LittleFS.remove(fp);
          }
          e.close();
          LittleFS.rmdir(path);
        } else {
          e.close();
          LittleFS.remove(path);
        }
      }
      d.close();
    }
  } else {
    // factory reset: NVS namespace wipe + filesystem format + BLE bonds.
    // Clears stats, owner, petname, species, settings, GIF characters,
    // and any stored LTKs so the next desktop has to re-pair.
    _prefs.begin("buddy", false);
    _prefs.clear();
    _prefs.end();
    LittleFS.format();
    bleClearBonds();
  }
  delay(300);
  ESP.restart();
}

void menuConfirm() {
  switch (screen::menu::selected()) {
    case 0: settingsOpen = true; menuOpen = false; screen::settings::setSelected(0); break;
    case 1: hal::power::powerOff(); break;
    case 2:
    case 3: {
      uint8_t sel = screen::menu::selected();
      menuOpen = false;
      displayMode = DISP_INFO;
      for (uint8_t i = 0; i < ((sel == 2) ? 1 : 5); i++) screen::info::nextPage();
      applyDisplayMode();
      characterInvalidate();
      break;
    }
    case 4: dataSetDemo(!dataDemo()); break;
    case 5: menuOpen = false; characterInvalidate(); break;
  }
}

// Forward declarations for functions defined later in this file
void triggerOneShot(PersonaState s, uint32_t durMs);

// Approval wrappers — called from screen::approval::handleButton.
// Keep the stats/beep/triggerOneShot logic here since stats.h is single-TU.
void approvalDoApprove() {
  if (responseSent) return;
  char cmd[96];
  snprintf(cmd, sizeof(cmd), "{\"cmd\":\"permission\",\"id\":\"%s\",\"decision\":\"once\"}", tama.promptId);
  sendCmd(cmd);
  responseSent = true;
  uint32_t tookS = (millis() - promptArrivedMs) / 1000;
  statsOnApproval(tookS);
  beep(2400, 60);
  if (tookS < 5) triggerOneShot(P_HEART, 2000);
}

void approvalDoDeny() {
  if (responseSent) return;
  char cmd[96];
  snprintf(cmd, sizeof(cmd), "{\"cmd\":\"permission\",\"id\":\"%s\",\"decision\":\"deny\"}", tama.promptId);
  sendCmd(cmd);
  responseSent = true;
  statsOnDenial();
  beep(600, 60);
}

// Input event synthesizer — called once per frame.
// Converts raw hal::buttons polls into (Button, ButtonEvent) calls on `emit`.
// Preserves tap-vs-long-press timing and first-press-on-wake swallow behavior.
template <typename Emit>
static void pollInput(Emit emit) {
  // ---- A button ----
  bool aNow = hal::buttons::pressedA();
  if (aNow && !bs.prevA) {
    // fresh press
    bs.aLongFired = false;
    if (screenOff) { swallowBtnA = true; }
    wake();
  }
  if (aNow && !bs.aLongFired && !swallowBtnA && hal::buttons::heldA(600)) {
    bs.aLongFired = true;
    beep(800, 60);
    emit(Btn::A, BtnEvent::LongPress);
  }
  if (!aNow && bs.prevA) {
    // released
    if (!bs.aLongFired && !swallowBtnA) {
      emit(Btn::A, BtnEvent::Tap);
    }
    bs.aLongFired  = false;
    swallowBtnA = false;
  }
  bs.prevA = aNow;

  // ---- B button ----
  bool bNow = hal::buttons::pressedB();
  if (bNow && !bs.prevB) {
    if (screenOff) { swallowBtnB = true; wake(); }
    else { wake(); }
    if (!swallowBtnB) {
      emit(Btn::B, BtnEvent::Tap);
    }
    swallowBtnB = false;
  }
  bs.prevB = bNow;

  // ---- Power button ----
  if (hal::buttons::powerButtonPressed()) {
    emit(Btn::Power, BtnEvent::Tap);
  }
}

// Clock orientation: gravity along the in-plane X axis means the stick is
// on its side. Signed counter for hysteresis on both transitions — same
// pattern as face-down nap.
//   0 = portrait (sprite path, pet sleeps underneath)
//   1 = landscape, BtnA-side down (M5.Display rotation 1)
//   3 = landscape, USB-side down (M5.Display rotation 3)
static uint8_t clockOrient   = 0;
static int8_t  orientFrames  = 0;
// RTC and IMU share an I2C bus. Reading the RTC at 60fps starves the IMU
// reads in clockUpdateOrient — orientation detection gets noisy. Cache the
// time once per second; mood logic and drawClock both read from here.
static hal::rtc::Time _clkTm;
static hal::rtc::Date _clkDt;
uint32_t               _clkLastRead = 0;   // zeroed by data.h on time-sync
static bool            _onUsb       = false;
static void clockRefreshRtc() {
  if (millis() - _clkLastRead < 1000) return;
  _clkLastRead = millis();
  _onUsb = hal::power::busVoltage() > 4.0f;
  hal::rtc::getTime(_clkTm);
  hal::rtc::getDate(_clkDt);
}

static void clockUpdateOrient() {
  float ax, ay, az;
  hal::imu::readAccel(ax, ay, az);
  uint8_t lock = settings().clockRot;
  if (lock == 1) { clockOrient = 0; return; }
  if (lock == 2) {
    // Locked landscape: never drop to 0, but still pick 1 vs 3 from
    // gravity so the cradle works either way up. Need a strong tilt
    // for the 1↔3 swap so handling jitter doesn't flip it; otherwise
    // hold whatever we last had (or 1 from boot).
    if (clockOrient == 0) clockOrient = (ax >= 0) ? 1 : 3;
    if      (ax >  0.5f && clockOrient != 1) clockOrient = 1;
    else if (ax < -0.5f && clockOrient != 3) clockOrient = 3;
    return;
  }
  // Dual threshold: strict to enter (must be clearly sideways), loose to
  // stay (tolerate ~65° of tilt). With one shared threshold a slight lean
  // while sitting on the long edge puts ax right at the boundary and the
  // counter ratchets down in ~half a second.
  bool side = (clockOrient == 0)
    ? fabsf(ax) > 0.7f && fabsf(ay) < 0.5f && fabsf(az) < 0.5f
    : fabsf(ax) > 0.4f;
  if (side) { if (orientFrames < 20) orientFrames++; }
  else      { if (orientFrames > -10) orientFrames--; }
  if (clockOrient == 0 && orientFrames >= 15) {
    clockOrient = (ax > 0) ? 1 : 3;
  } else if (clockOrient != 0 && orientFrames <= -8) {
    clockOrient = 0;
  } else if (clockOrient != 0 && side) {
    // Direct 1↔3: a fast flip keeps |ax|>0.7 (just changes sign), so
    // `side` never drops and the exit-via-0 path can't fire. Watch for
    // ax sign disagreeing with the stored orientation.
    static int8_t swapFrames = 0;
    uint8_t want = (ax > 0) ? 1 : 3;
    if (want != clockOrient) { if (++swapFrames >= 8) { clockOrient = want; swapFrames = 0; } }
    else swapFrames = 0;
  }
}

// Clock face: shown when charging on USB with nothing else going on.
// Portrait paints the upper ~110px to the sprite; pet renders below.
// Landscape draws direct to LCD with rotation — sprite stays untouched.
// Clock face drawing moved to screens/clock.cpp; see screen::clock::draw()

PersonaState derive(const TamaState& s) {
  if (!s.connected)            return P_IDLE;
  if (s.sessionsWaiting > 0)   return P_ATTENTION;
  if (s.recentlyCompleted)     return P_CELEBRATE;
  if (s.sessionsRunning >= 3)  return P_BUSY;
  return P_IDLE;   // connected, 0+ sessions, nothing urgent — hang out
}

void triggerOneShot(PersonaState s, uint32_t durMs) {
  activeState = s;
  oneShotUntil = millis() + durMs;
}

bool checkShake() {
  float ax, ay, az;
  hal::imu::readAccel(ax, ay, az);
  float mag = sqrtf(ax*ax + ay*ay + az*az);
  float delta = fabsf(mag - accelBaseline);
  accelBaseline = accelBaseline * 0.95f + mag * 0.05f;
  return delta > 0.8f;
}




// Persistent screen-level title row ("INFO  n/3") matching the PET header,
// then a per-page section label below it. The fixed title is the cue that
// B cycles pages here just like it does on PET.


// Greedy word-wrap into fixed-width rows. Continuation rows get a leading
// space. Returns number of rows written.
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



void setup() {
  hal::begin();
  startBt();
  pinMode(LED_PIN, OUTPUT);
  digitalWrite(LED_PIN, HIGH);   // off
  applyBrightness();
  lastInteractMs = millis();
  statsLoad();
  settingsLoad();
  petNameLoad();
  buddyInit();

  // BLE stays always-on; s.bt is stored as a preference only.
  characterInit(nullptr);  // scan /characters/ for whatever is installed
  gifAvailable = characterLoaded();
  // species NVS: 0..N-1 = ASCII species, 0xFF = use GIF (also the default,
  // so a fresh install lands on the GIF). With no GIF installed, 0xFF falls
  // through to buddyInit()'s clamped default.
  buddyMode = !(gifAvailable && speciesIdxLoad() == SPECIES_GIF);
  applyDisplayMode();

  {
    const Palette& p = characterPalette();
    canvas.fillSprite(p.bg);
    canvas.setTextDatum(MC_DATUM);
    canvas.setTextSize(2);
    if (ownerName()[0]) {
      char line[40];
      snprintf(line, sizeof(line), "%s's", ownerName());
      canvas.setTextColor(p.text, p.bg);   canvas.drawString(line, W/2, H/2 - 12);
      canvas.setTextColor(p.body, p.bg);   canvas.drawString(petName(), W/2, H/2 + 12);
    } else {
      // First boot, no owner pushed yet — say hi.
      canvas.setTextColor(p.body, p.bg);   canvas.drawString("Hello!", W/2, H/2 - 12);
      canvas.setTextSize(1);
      canvas.setTextColor(p.textDim, p.bg);
      canvas.drawString("a buddy appears", W/2, H/2 + 12);
    }
    canvas.setTextDatum(TL_DATUM); canvas.setTextSize(1);
    hal::display::push();
    delay(1800);
  }

  Serial.printf("buddy: %s\n", buddyMode ? "ASCII mode" : "GIF character loaded");

#ifdef NATIVE_BUILD
  // Emulator hook: EMULATOR_DEMO=1 enables demo mode at boot so the HUD
  // gets fake transcript/session data to render. Without this, the
  // emulator stays on the "no Claude connected" path forever and we
  // can't capture HUD layouts in the screenshot harness.
  if (getenv("EMULATOR_DEMO")) dataSetDemo(true);
#endif
}

void loop() {
  hal::tick();
  t++;
  uint32_t now = millis();

  dataPoll(&tama);
  if (statsPollLevelUp()) triggerOneShot(P_CELEBRATE, 3000);
  baseState = derive(tama);

  // After waking the screen, hold sleep for 12s so users see the wake-up
  // animation. Urgent states (attention, celebrate, busy) override this.
  if (baseState == P_IDLE && (int32_t)(now - wakeTransitionUntil) < 0) baseState = P_SLEEP;

  if ((int32_t)(now - oneShotUntil) >= 0) activeState = baseState;

  // LED: pulse on attention, otherwise off
  if (activeState == P_ATTENTION && settings().led) {
    digitalWrite(LED_PIN, (now / 400) % 2 ? LOW : HIGH);
  } else {
    digitalWrite(LED_PIN, HIGH);
  }

  // shake → dizzy + force scenario advance
  if (now - lastShakeCheck > 50) {
    lastShakeCheck = now;
    if (!menuOpen && !screenOff && checkShake() && (int32_t)(now - oneShotUntil) >= 0) {
      wake();
      triggerOneShot(P_DIZZY, 2000);
      Serial.println("shake: dizzy");
    }
  }

  // BtnA: step through fake scenarios
  // Prompt arrival: beep, reset response flag
  if (strcmp(tama.promptId, lastPromptId) != 0) {
    strncpy(lastPromptId, tama.promptId, sizeof(lastPromptId)-1);
    lastPromptId[sizeof(lastPromptId)-1] = 0;
    responseSent = false;
    if (tama.promptId[0]) {
      promptArrivedMs = millis();
      wake();
      beep(1200, 80);   // alert chirp
      // Jump to the approval screen no matter what was open.
      displayMode = DISP_NORMAL;
      menuOpen = settingsOpen = resetOpen = false;
      applyDisplayMode();
      characterInvalidate();
      if (buddyMode) buddyInvalidate();
    }
  }

  bool inPrompt = tama.promptId[0] && !responseSent;

  // Input event dispatch — synthesize (Button, ButtonEvent) from raw polls,
  // route to the active screen's handleButton first, then fall back to global
  // actions. The wake/swallow logic lives inside pollInput.
  pollInput([&](Btn b, BtnEvent e) {
    bool consumed = false;

    // Route to active screen
    if      (resetOpen)              consumed = screen::reset::handleButton(b, e);
    else if (settingsOpen)           consumed = screen::settings::handleButton(b, e);
    else if (menuOpen)               consumed = screen::menu::handleButton(b, e);
    else if (inPrompt)               consumed = screen::approval::handleButton(b, e);
    else if (displayMode == DISP_PET) consumed = screen::petstats::handleButton(b, e);

    if (consumed) return;

    // Global fallback
    if (b == Btn::Power) {
      // AXP power button: short-press toggles screen off (long-press handled by AXP HW)
      if (screenOff) { wake(); }
      else { hal::power::setLcdPower(false); screenOff = true; }
      return;
    }

    if (b == Btn::A && e == BtnEvent::LongPress) {
      // Long-press A: open/close menu or escape from sub-screens
      if (resetOpen) { resetOpen = false; }
      else if (settingsOpen) { settingsOpen = false; characterInvalidate(); }
      else {
        menuOpen = !menuOpen;
        screen::menu::setSelected(0);
        if (!menuOpen) characterInvalidate();
      }
      Serial.println(menuOpen ? "menu open" : "menu close");
      return;
    }

    if (b == Btn::A && e == BtnEvent::Tap) {
      // A-tap global: cycle display mode
      beep(1800, 30);
      displayMode = (displayMode + 1) % DISP_COUNT;
      applyDisplayMode();
      return;
    }

    if (b == Btn::B && e == BtnEvent::Tap) {
      // B-tap global: activate / scroll depending on context
      if (resetOpen) {
        beep(2400, 30);
        applyReset(screen::reset::selected());
      } else if (settingsOpen) {
        beep(2400, 30);
        applySetting(screen::settings::selected());
      } else if (menuOpen) {
        beep(2400, 30);
        menuConfirm();
      } else if (displayMode == DISP_INFO) {
        beep(2400, 30);
        screen::info::nextPage();
      } else {
        beep(2400, 30);
        screen::hud::scrollMessage();
      }
      return;
    }
  });

  // blink bookkeeping

  // Charging clock: takes over the home screen when on USB power, no
  // overlays, no prompt, no live Claude data, and the RTC has been set
  // by the bridge. Pet sleeps underneath. Exit restores Y via
  // applyDisplayMode() so the next mode-switch isn't visually offset.
  clockRefreshRtc();   // 1Hz internal throttle; also caches _onUsb
  bool clocking = false;
  if (clocking) clockUpdateOrient();
  else { clockOrient = 0; orientFrames = 0; }
  bool landscapeClock = clocking && clockOrient != 0;

  static bool wasClocking = false;
  static bool wasLandscape = false;
  if (clocking != wasClocking || landscapeClock != wasLandscape) {
    if (clocking && !landscapeClock) characterSetPeek(true);
    else applyDisplayMode();
    characterInvalidate();
    if (buddyMode) buddyInvalidate();
    wasClocking = clocking;
    wasLandscape = landscapeClock;
  }
  if (clocking) {
    uint8_t dow = _clkDt.weekday % 7;
    bool weekend = (dow == 0 || dow == 6);
    bool friday  = (dow == 5);

    uint8_t h = _clkTm.h;
    if (h >= 1 && h < 7)             activeState = P_SLEEP;
    else if (weekend)                activeState = (now/8000 % 6 == 0) ? P_HEART : P_SLEEP;
    else if (h < 9)                  activeState = (now/6000 % 4 == 0) ? P_IDLE  : P_SLEEP;
    else if (h == 12)                activeState = (now/5000 % 3 == 0) ? P_HEART : P_IDLE;
    else if (friday && h >= 15)      activeState = (now/4000 % 3 == 0) ? P_CELEBRATE : P_IDLE;
    else if (h >= 22 || h == 0)      activeState = (now/7000 % 3 == 0) ? P_DIZZY : P_SLEEP;
    else                             activeState = (now/10000 % 5 == 0) ? P_SLEEP : P_IDLE;
  }

  static uint32_t lastPasskey = 0;
  uint32_t pk = blePasskey();
  if (pk && !lastPasskey) { wake(); beep(1800, 60); }
  lastPasskey = pk;

  // Send evt:info once on every BLE connection edge (false → true). The
  // bridge reads `version` to decide if an OTA is needed and `features`
  // to gate which cmd:* it can safely send. xfer_v1 is the existing
  // file-transfer protocol; ota_v1 will be added by step 4 once the
  // device-side OTA state machine lands.
  static bool _wasConnected = false;
  bool nowConnected = bleConnected();
  if (nowConnected && !_wasConnected) {
    char info[160];
    const char* board =
#if defined(ARDUINO_M5STACK_Core2)
      "m5stack-core2";
#else
      "m5stickc-plus";
#endif
    snprintf(info, sizeof(info),
      "{\"evt\":\"info\",\"board\":\"%s\",\"version\":\"%s\",\"features\":[\"xfer_v1\",\"ota_v1\"]}",
      board, BUILD_VERSION);
    sendCmd(info);
  }
  _wasConnected = nowConnected;

  // Drain pending evt:ota_* messages produced by ota::handle_command,
  // and tick the state machine (triggers the deferred ESP.restart()
  // after the post-commit grace period).
  char ota_evt[160];
  while (ota::poll_event(ota_evt, sizeof(ota_evt))) {
    sendCmd(ota_evt);
  }
  ota::tick();

  if (napping || screenOff || landscapeClock || displayMode == DISP_INFO) {
    // skip sprite render — face-down, powered off, landscape clock (which
    // draws direct-to-LCD below), or info mode (which paints the whole
    // screen itself, no buddy header).
  } else if (buddyMode) {
    buddyTick(activeState);
  } else if (characterLoaded()) {
    characterSetState(activeState);
    characterTick();
  } else {
    const Palette& p = characterPalette();
    canvas.fillSprite(p.bg);
    canvas.setTextColor(p.textDim, p.bg);
    canvas.setTextSize(1);
    if (xferActive()) {
      uint32_t done = xferProgress(), total = xferTotal();
      canvas.setCursor(8, 90);
      canvas.print("installing");
      canvas.setCursor(8, 102);
      canvas.printf("%luK / %luK", done/1024, total/1024);
      int barW = W - 16;
      canvas.drawRect(8, 116, barW, 8, p.textDim);
      if (total > 0) {
        int fill = (int)((uint64_t)barW * done / total);
        if (fill > 1) canvas.fillRect(9, 117, fill - 1, 6, p.body);
      }
    } else {
      canvas.setCursor(8, 100);
      canvas.print("no character loaded");
    }
  }
  if (landscapeClock) {
    screen::clock::draw(clockOrient, _clkTm, _clkDt);
  } else if (!napping && !screenOff) {
    if (blePasskey()) screen::passkey::draw();
    else if (clocking) screen::clock::draw(clockOrient, _clkTm, _clkDt);
    else if (displayMode == DISP_INFO) screen::info::draw();
    else if (displayMode == DISP_PET) screen::petstats::draw();
    else if (settings().hud) {
      if (tama.promptId[0]) screen::approval::draw();
      else                  screen::hud::draw();
    }
    if (resetOpen) screen::reset::draw();
    else if (settingsOpen) screen::settings::draw();
    else if (menuOpen) screen::menu::draw();
    hal::display::push();
  }

  // Face-down nap: dim immediately, pause animations, accumulate sleep time.
  // Skipped during approval — you're holding it to read, not sleeping it.
  // Exit needs sustained not-down so IMU noise at the threshold doesn't
  // bounce brightness between 8 and full every few frames.
  static int8_t faceDownFrames = 0;
  if (!inPrompt) {
    bool down = isFaceDown();
    if (down)       { if (faceDownFrames < 20) faceDownFrames++; }
    else            { if (faceDownFrames > -10) faceDownFrames--; }
  }

  if (!napping && faceDownFrames >= 15) {
    napping = true;
    napStartMs = now;
    hal::power::setBrightness(0);
    dimmed = true;
  } else if (napping && faceDownFrames <= -8) {
    napping = false;
    statsOnNapEnd((now - napStartMs) / 1000);
    statsOnWake();
    wake();
  }

  // millis() not the cached `now`: wake() runs after `now` is captured,
  // so now - lastInteractMs underflows when a button is held → flicker.
  // No auto-off on USB power — clock face wants to stay visible while charging.
  if (!screenOff && !inPrompt && !_onUsb
      && millis() - lastInteractMs > SCREEN_OFF_MS) {
    hal::power::setLcdPower(false);
    screenOff = true;
  }

  delay(screenOff ? 100 : 16);
}
