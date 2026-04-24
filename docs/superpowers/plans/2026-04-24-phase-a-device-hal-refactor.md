# Phase A — Device HAL & Screen Refactor — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Isolate all M5StickC-specific hardware calls behind a narrow `hal::*` layer and extract the ~15 screen-drawing functions from `main.cpp` into focused per-screen modules, so that a future Core2 port is additive (new files, no shared-code rewrite).

**Architecture:** Free-function namespaces for the HAL (`hal::display`, `hal::buttons`, `hal::imu`, `hal::power`, `hal::beep`, `hal::rtc`) in `src/hal/`. Per-screen modules in `src/screens/` each exposing `draw()` and optionally `handleButton()`. `main.cpp` shrinks to lifecycle + state machine + input-event synthesis. No `#ifdef DEVICE_*` in app code — Phase B will select per-device implementations via PlatformIO `build_src_filter`.

**Tech Stack:** PlatformIO, Arduino, ESP32, M5StickCPlus library, TFT_eSPI, LittleFS, BLE (ESP-IDF).

**Verification model (no test harness in this project):** Every task ends with a build + on-device flash + manual smoke check of the affected behavior. The project has no unit tests and cannot host them (hardware-dependent code). "TDD" here means *change → verify parity → commit*, not test-first.

**Build / flash commands** (used throughout; assume present in the agent's environment):

```bash
# Build only
/Users/stephenoliver/.platformio/penv/bin/pio run

# Build + upload (preserves NVS: flash ranges are bootloader / partition table /
# otadata / app only — NVS at 0x9000-0xdfff is untouched)
/Users/stephenoliver/.platformio/penv/bin/pio run -t upload
```

**Code-level invariant** (re-check at the end of every task):

```bash
grep -rn "M5\." src/ --exclude-dir=hal | grep -v "^Binary"
```

After A.2 completes this should return zero matches outside `src/hal/`.

---

## File Structure (post-refactor)

**New files** (all created during this plan):

```
src/input.h                        ← Button/ButtonEvent enums (A.4)
src/hal/hal.h
src/hal/hal.cpp
src/hal/display.h
src/hal/display.cpp
src/hal/buttons.h
src/hal/buttons.cpp
src/hal/imu.h
src/hal/imu.cpp
src/hal/power.h
src/hal/power.cpp
src/hal/beep.h
src/hal/beep.cpp
src/hal/rtc.h
src/hal/rtc.cpp
src/screens/clock.h        / .cpp
src/screens/stats.h        / .cpp
src/screens/passkey.h      / .cpp
src/screens/approval.h     / .cpp
src/screens/menu.h         / .cpp
src/screens/settings.h     / .cpp
src/screens/reset.h        / .cpp
src/screens/hud.h          / .cpp
src/screens/info.h         / .cpp
```

**Modified files:** `src/main.cpp` (progressively shrinks), `src/data.h` (one `M5.Rtc` call), `src/xfer.h` (three `M5.Axp` calls), `src/character.cpp` (`spr` init), `src/buddy.cpp` (`spr` init). No changes to `ble_bridge.*`, `stats.h`, `buddy_common.h`, `character.h`, `buddy.h`, or any `buddies/*.cpp`.

**No changes to `platformio.ini`** — the existing `build_src_filter = +<*> +<buddies/>` already picks up new subdirectories.

---

## Task 1 — A.1: HAL scaffolding

**Goal:** Create the entire `src/hal/` directory with working declarations and implementations that delegate directly to `M5.*`. No call sites migrated yet. Build passes. No flash needed (no behavior change).

**Files:**
- Create: `src/hal/hal.h`, `src/hal/hal.cpp`
- Create: `src/hal/display.h`, `src/hal/display.cpp`
- Create: `src/hal/buttons.h`, `src/hal/buttons.cpp`
- Create: `src/hal/imu.h`, `src/hal/imu.cpp`
- Create: `src/hal/power.h`, `src/hal/power.cpp`
- Create: `src/hal/beep.h`, `src/hal/beep.cpp`
- Create: `src/hal/rtc.h`, `src/hal/rtc.cpp`

**Important:** in A.1, `hal::display::sprite()` returns a reference to the existing `extern TFT_eSprite spr` still declared in `main.cpp`. Ownership moves in Task 7 (A.2.6). This lets every earlier HAL task compile cleanly without touching the sprite lifetime.

- [ ] **Step 1: Create `src/hal/hal.h`**

```cpp
#pragma once

namespace hal {
  // M5.begin() + display/beep/imu init. Call once from setup().
  void begin();
  // M5.update() + per-frame bookkeeping. Call once per loop().
  void tick();
}
```

- [ ] **Step 2: Create `src/hal/hal.cpp`**

```cpp
#include "hal.h"
#include "display.h"
#include "beep.h"
#include <M5StickCPlus.h>

namespace hal {

void begin() {
  M5.begin();
  display::begin();
  M5.Imu.Init();
  beep::begin();
}

void tick() {
  M5.update();
  beep::tick();
}

} // namespace hal
```

- [ ] **Step 3: Create `src/hal/display.h`**

```cpp
#pragma once
#include <TFT_eSPI.h>

namespace hal { namespace display {
  void begin();                    // no-op in A.1; owns sprite from A.2.6
  TFT_eSPI&    lcd();              // direct LCD (landscape clock, passkey)
  TFT_eSprite& sprite();           // shared drawing surface
  int  width();                    // 135 on StickC Plus
  int  height();                   // 240
  void setRotation(uint8_t r);     // 0..3
  void push();                     // sprite → LCD (sprite.pushSprite(0, 0))
}}
```

- [ ] **Step 4: Create `src/hal/display.cpp`**

In A.1 this delegates to the still-`main.cpp`-owned `spr`. Ownership migrates in Task 7.

```cpp
#include "display.h"
#include <M5StickCPlus.h>

extern TFT_eSprite spr;  // still lives in main.cpp during A.1..A.2.5

namespace hal { namespace display {

void begin()                 { /* sprite init still in main.cpp setup() */ }
TFT_eSPI&    lcd()           { return M5.Lcd; }
TFT_eSprite& sprite()        { return spr; }
int  width()                 { return 135; }
int  height()                { return 240; }
void setRotation(uint8_t r)  { M5.Lcd.setRotation(r); }
void push()                  { spr.pushSprite(0, 0); }

}}
```

- [ ] **Step 5: Create `src/hal/buttons.h`**

```cpp
#pragma once
#include <stdint.h>

namespace hal { namespace buttons {
  bool pressedA();
  bool pressedB();
  bool heldA(uint16_t ms);              // M5.BtnA.pressedFor(ms)
  bool powerButtonPressed();            // AXP side-button tap (GetBtnPress() == 0x02)
}}
```

- [ ] **Step 6: Create `src/hal/buttons.cpp`**

```cpp
#include "buttons.h"
#include <M5StickCPlus.h>

namespace hal { namespace buttons {

bool pressedA()             { return M5.BtnA.isPressed(); }
bool pressedB()             { return M5.BtnB.isPressed(); }
bool heldA(uint16_t ms)     { return M5.BtnA.pressedFor(ms); }
bool powerButtonPressed()   { return M5.Axp.GetBtnPress() == 0x02; }

}}
```

- [ ] **Step 7: Create `src/hal/imu.h`**

```cpp
#pragma once

namespace hal { namespace imu {
  void readAccel(float& ax, float& ay, float& az);
}}
```

- [ ] **Step 8: Create `src/hal/imu.cpp`**

```cpp
#include "imu.h"
#include <M5StickCPlus.h>

namespace hal { namespace imu {

void readAccel(float& ax, float& ay, float& az) {
  M5.Imu.getAccelData(&ax, &ay, &az);
}

}}
```

- [ ] **Step 9: Create `src/hal/power.h`**

```cpp
#pragma once
#include <stdint.h>

namespace hal { namespace power {
  float busVoltage();                 // VBus in volts (> 4.0 = USB attached)
  float batVoltage();                 // battery V
  float batCurrent();                 // battery current (mA)
  float axpTemp();                    // AXP192 die temperature (°C)
  void  setBrightness(uint8_t level); // 0..5 — ScreenBreath(20 + level*20)
  void  setLcdPower(bool on);         // LDO2 rail — LCD backlight/power
  void  powerOff();                   // hard shutdown
}}
```

- [ ] **Step 10: Create `src/hal/power.cpp`**

```cpp
#include "power.h"
#include <M5StickCPlus.h>

namespace hal { namespace power {

float busVoltage() { return M5.Axp.GetVBusVoltage(); }
float batVoltage() { return M5.Axp.GetBatVoltage(); }
float batCurrent() { return M5.Axp.GetBatCurrent(); }
float axpTemp()    { return M5.Axp.GetTempInAXP192(); }

void setBrightness(uint8_t level) { M5.Axp.ScreenBreath(20 + level * 20); }
void setLcdPower(bool on)         { M5.Axp.SetLDO2(on); }
void powerOff()                   { M5.Axp.PowerOff(); }

}}
```

- [ ] **Step 11: Create `src/hal/beep.h`**

```cpp
#pragma once
#include <stdint.h>

namespace hal { namespace beep {
  void begin();
  void tick();
  void tone(uint16_t freq, uint16_t ms); // raw — caller gates on settings
}}
```

- [ ] **Step 12: Create `src/hal/beep.cpp`**

```cpp
#include "beep.h"
#include <M5StickCPlus.h>

namespace hal { namespace beep {

void begin()                              { M5.Beep.begin(); }
void tick()                               { M5.Beep.update(); }
void tone(uint16_t freq, uint16_t ms)     { M5.Beep.tone(freq, ms); }

}}
```

- [ ] **Step 13: Create `src/hal/rtc.h`**

```cpp
#pragma once
#include <stdint.h>

namespace hal { namespace rtc {

struct Time { uint8_t h, m, s; };
struct Date { uint8_t weekday, month, day; uint16_t year; };

void getTime(Time& out);
void getDate(Date& out);
void setTime(const Time& in);
void setDate(const Date& in);

}}
```

- [ ] **Step 14: Create `src/hal/rtc.cpp`**

```cpp
#include "rtc.h"
#include <M5StickCPlus.h>

namespace hal { namespace rtc {

void getTime(Time& out) {
  RTC_TimeTypeDef t;
  M5.Rtc.GetTime(&t);
  out.h = t.Hours; out.m = t.Minutes; out.s = t.Seconds;
}

void getDate(Date& out) {
  RTC_DateTypeDef d;
  M5.Rtc.GetDate(&d);
  out.weekday = d.WeekDay;
  out.month   = d.Month;
  out.day     = d.Date;
  out.year    = d.Year;
}

void setTime(const Time& in) {
  RTC_TimeTypeDef t{};
  t.Hours = in.h; t.Minutes = in.m; t.Seconds = in.s;
  M5.Rtc.SetTime(&t);
}

void setDate(const Date& in) {
  RTC_DateTypeDef d{};
  d.WeekDay = in.weekday;
  d.Month   = in.month;
  d.Date    = in.day;
  d.Year    = in.year;
  M5.Rtc.SetDate(&d);
}

}}
```

- [ ] **Step 15: Build**

```bash
/Users/stephenoliver/.platformio/penv/bin/pio run
```

Expected: `SUCCESS`. No link errors (the new `.cpp` files reference `spr` which is still in `main.cpp`; that `extern` in `hal/display.cpp` resolves to the existing symbol).

No flash — nothing in the firmware actually calls the HAL yet.

- [ ] **Step 16: Commit**

```bash
git add src/hal/
git commit -m "Add hal/ scaffolding (no call sites migrated yet)"
```

---

## Task 2 — A.2.1: Migrate `beep` callers

**Goal:** Replace every `M5.Beep.*` call in `main.cpp` with `hal::beep::*`. The `beep()` helper in `main.cpp` stays (it gates on `settings().sound`) but calls the HAL underneath.

**Files:**
- Modify: `src/main.cpp`

**Current call sites** (from `grep -n "M5\.Beep" src/main.cpp`):
- `line ~112`: `M5.Beep.tone(freq, dur)` inside `beep()` helper
- `line ~947`: `M5.Beep.begin()` in `setup()` — **removed** (done inside `hal::begin()`)
- `line ~995`: `M5.Beep.update()` in `loop()` — **removed** (done inside `hal::tick()`)

- [ ] **Step 1: Replace `M5.Beep.tone` in the `beep()` helper**

In `main.cpp`, find:

```cpp
static void beep(uint16_t freq, uint16_t dur) {
  if (settings().sound) M5.Beep.tone(freq, dur);
}
```

Replace with:

```cpp
static void beep(uint16_t freq, uint16_t dur) {
  if (settings().sound) hal::beep::tone(freq, dur);
}
```

- [ ] **Step 2: Remove `M5.Beep.begin()` from `setup()`**

Find `M5.Beep.begin();` in `setup()` and delete the line. `hal::begin()` (to be wired in a later task) will call it. For now `M5.begin()` still runs in setup too; that remains until Task 8.

- [ ] **Step 3: Remove `M5.Beep.update()` from `loop()`**

Find `M5.Beep.update();` in `loop()` and delete the line. `M5.update()` still runs; that stays until Task 8 swaps it for `hal::tick()`.

- [ ] **Step 4: Add `#include "hal/beep.h"` near the other includes in `main.cpp`**

Near the top of `main.cpp`, after existing includes:

```cpp
#include "hal/beep.h"
```

- [ ] **Step 5: Temporary init**

Because `hal::begin()` isn't being called yet (that's Task 8), but we just removed `M5.Beep.begin()`, we need an interim `hal::beep::begin()` call in `setup()` so audio still works:

In `setup()`, replace the old `M5.Beep.begin();` location with:

```cpp
hal::beep::begin();
```

Similarly in `loop()`, replace the removed `M5.Beep.update();` with:

```cpp
hal::beep::tick();
```

- [ ] **Step 6: Build**

```bash
/Users/stephenoliver/.platformio/penv/bin/pio run
```

Expected: `SUCCESS`.

- [ ] **Step 7: Flash**

```bash
/Users/stephenoliver/.platformio/penv/bin/pio run -t upload
```

- [ ] **Step 8: Smoke test**

On device: long-hold A to open the menu. Each nav tick should still beep. Dismiss menu. Trigger a prompt via Claude Desktop (or wait for any approval path) — approval should still beep.

Expected: beeps still fire, indistinguishable from pre-change.

- [ ] **Step 9: Commit**

```bash
git add src/main.cpp
git commit -m "Migrate beep callers to hal::beep"
```

---

## Task 3 — A.2.2: Migrate `rtc` callers

**Goal:** Replace `M5.Rtc.*` calls with `hal::rtc::*` in `data.h` (setter) and `main.cpp` (getter in `clockRefreshRtc`). Translates between the plain `hal::rtc::Time`/`Date` structs and the internal storage.

**Files:**
- Modify: `src/data.h` (the line containing `M5.Rtc.SetTime` / `M5.Rtc.SetDate`)
- Modify: `src/main.cpp` (the `clockRefreshRtc` function and any `DOW`/`MON` / date rendering)

**Note:** `main.cpp` currently caches date/time into `_clkTm` and `_clkDt` of type `RTC_TimeTypeDef` / `RTC_DateTypeDef`. Part of this task is switching those caches to the HAL structs. Everything that *reads* from the cache (`drawClock`, mood calc, etc.) needs to use the new field names (`h/m/s` instead of `Hours/Minutes/Seconds`, `weekday/month/day` instead of `WeekDay/Month/Date`).

- [ ] **Step 1: Add include to `main.cpp`**

```cpp
#include "hal/rtc.h"
```

- [ ] **Step 2: Change `_clkTm` / `_clkDt` cache types**

Find:

```cpp
static RTC_TimeTypeDef _clkTm;
static RTC_DateTypeDef _clkDt;
```

Replace with:

```cpp
static hal::rtc::Time _clkTm;
static hal::rtc::Date _clkDt;
```

- [ ] **Step 3: Update `clockRefreshRtc()` body**

Find:

```cpp
static void clockRefreshRtc() {
  ...
  _onUsb = M5.Axp.GetVBusVoltage() > 4.0f;
  M5.Rtc.GetTime(&_clkTm);
  M5.Rtc.GetDate(&_clkDt);
}
```

Replace the two Rtc calls (leave `_onUsb` alone — `power` migration handles it in the next task):

```cpp
static void clockRefreshRtc() {
  ...
  _onUsb = M5.Axp.GetVBusVoltage() > 4.0f;
  hal::rtc::getTime(_clkTm);
  hal::rtc::getDate(_clkDt);
}
```

- [ ] **Step 4: Update all readers of `_clkTm` / `_clkDt`**

Grep for usages (`grep -n "_clkTm\|_clkDt" src/main.cpp`) and rename field accesses:
- `_clkTm.Hours` → `_clkTm.h`
- `_clkTm.Minutes` → `_clkTm.m`
- `_clkTm.Seconds` → `_clkTm.s`
- `_clkDt.WeekDay` → `_clkDt.weekday`
- `_clkDt.Month` → `_clkDt.month`
- `_clkDt.Date` → `_clkDt.day`
- `_clkDt.Year` → `_clkDt.year` (if referenced; probably not)

Every occurrence in `drawClock()`, `clockDow()`, and anywhere mood/energy code reads the clock. Leave no `_clkTm.Hours`-style references behind.

- [ ] **Step 5: Migrate `data.h`**

Add include at top of `data.h`:

```cpp
#include "hal/rtc.h"
```

Find the block (around line 80-85):

```cpp
M5.Rtc.SetTime(&tm);
M5.Rtc.SetDate(&dt);
```

Replace with translation to HAL structs. The `tm` and `dt` there are of type `RTC_TimeTypeDef` / `RTC_DateTypeDef` populated earlier in the function. Replace with HAL equivalents by translating the values. Full code block context — find something like:

```cpp
RTC_TimeTypeDef tm; tm.Hours = ...; tm.Minutes = ...; tm.Seconds = ...;
RTC_DateTypeDef dt; dt.WeekDay = ...; dt.Month = ...; dt.Date = ...; dt.Year = ...;
M5.Rtc.SetTime(&tm);
M5.Rtc.SetDate(&dt);
```

Replace with:

```cpp
hal::rtc::Time tm; tm.h = ...; tm.m = ...; tm.s = ...;
hal::rtc::Date dt; dt.weekday = ...; dt.month = ...; dt.day = ...; dt.year = ...;
hal::rtc::setTime(tm);
hal::rtc::setDate(dt);
```

Read `data.h` around the existing setter to see the exact field assignments and copy them across with the renamed fields.

- [ ] **Step 6: Build**

```bash
/Users/stephenoliver/.platformio/penv/bin/pio run
```

Expected: `SUCCESS`. Compile errors in this step usually mean a `_clkTm.Hours`-style reference was missed in Step 4 — re-grep.

- [ ] **Step 7: Flash + smoke test**

```bash
/Users/stephenoliver/.platformio/penv/bin/pio run -t upload
```

Smoke test: the clock mode is currently hard-disabled (`main.cpp:1150` has `bool clocking = false;`), so there's no visible clock. But the RTC is still read by `clockRefreshRtc()` and used for time-of-day-based mood logic. Verify the device still boots, character renders, and no crash after a minute of uptime.

Bonus: trigger a bridge sync from Claude Desktop — the desktop sends an RTC-set message through the bridge; this should still take effect (no runtime crash from the translated setter).

- [ ] **Step 8: Commit**

```bash
git add src/main.cpp src/data.h
git commit -m "Migrate rtc callers to hal::rtc + plain structs"
```

---

## Task 4 — A.2.3: Migrate `power` callers

**Goal:** Replace all `M5.Axp.*` calls (brightness, USB detection, LCD power, poweroff, battery telemetry) with `hal::power::*`.

**Files:**
- Modify: `src/main.cpp`
- Modify: `src/xfer.h`

**Call sites (grep `M5\.Axp` in src/):**

| Location | Call | Replacement |
|---|---|---|
| `main.cpp:97` `applyBrightness()` | `M5.Axp.ScreenBreath(20 + brightLevel * 20)` | `hal::power::setBrightness(brightLevel)` |
| `main.cpp:102` wake | `M5.Axp.SetLDO2(true)` | `hal::power::setLcdPower(true)` |
| `main.cpp:308` menu reset action | `M5.Axp.PowerOff()` | `hal::power::powerOff()` |
| `main.cpp:359` `clockRefreshRtc` | `M5.Axp.GetVBusVoltage() > 4.0f` | `hal::power::busVoltage() > 4.0f` |
| `main.cpp:596-598` info panel | `GetBatVoltage / GetBatCurrent / GetVBusVoltage` | `hal::power::batVoltage / batCurrent / busVoltage` |
| `main.cpp:630` info panel | `GetTempInAXP192()` | `hal::power::axpTemp()` |
| `main.cpp:1065` power button sleep | `M5.Axp.SetLDO2(false)` | `hal::power::setLcdPower(false)` |
| `xfer.h:115-117` | `GetBatVoltage / GetBatCurrent / GetVBusVoltage` | same |

- [ ] **Step 1: Add include in `main.cpp`**

```cpp
#include "hal/power.h"
```

- [ ] **Step 2: Add include in `xfer.h`**

At the top of `xfer.h`:

```cpp
#include "hal/power.h"
```

- [ ] **Step 3: Replace in `applyBrightness()`**

Find:

```cpp
static void applyBrightness() { M5.Axp.ScreenBreath(20 + brightLevel * 20); }
```

Replace with:

```cpp
static void applyBrightness() { hal::power::setBrightness(brightLevel); }
```

- [ ] **Step 4: Replace wake's LDO2 call**

Find the call in `wake()` around line 102:

```cpp
M5.Axp.SetLDO2(true);
```

Replace:

```cpp
hal::power::setLcdPower(true);
```

- [ ] **Step 5: Replace poweroff**

Find:

```cpp
case 1: M5.Axp.PowerOff(); break;
```

Replace:

```cpp
case 1: hal::power::powerOff(); break;
```

- [ ] **Step 6: Replace USB-voltage check in `clockRefreshRtc`**

Find:

```cpp
_onUsb = M5.Axp.GetVBusVoltage() > 4.0f;
```

Replace:

```cpp
_onUsb = hal::power::busVoltage() > 4.0f;
```

- [ ] **Step 7: Replace info-panel telemetry reads (`main.cpp`)**

Around line 596-598 and 630, find the batch:

```cpp
int vBat_mV = (int)(M5.Axp.GetBatVoltage() * 1000);
int iBat_mA = (int)M5.Axp.GetBatCurrent();
int vBus_mV = (int)(M5.Axp.GetVBusVoltage() * 1000);
```

Replace:

```cpp
int vBat_mV = (int)(hal::power::batVoltage() * 1000);
int iBat_mA = (int)hal::power::batCurrent();
int vBus_mV = (int)(hal::power::busVoltage() * 1000);
```

And the temperature line (line ~630):

```cpp
ln("  temp     %dC", (int)M5.Axp.GetTempInAXP192());
```

Replace:

```cpp
ln("  temp     %dC", (int)hal::power::axpTemp());
```

- [ ] **Step 8: Replace the sleep SetLDO2 call**

Find:

```cpp
M5.Axp.SetLDO2(false);
```

(in the power-button handler near line 1065). Replace:

```cpp
hal::power::setLcdPower(false);
```

- [ ] **Step 9: Replace in `xfer.h`**

Around line 115-117 find the same `GetBatVoltage / GetBatCurrent / GetVBusVoltage` triplet. Replace with the `hal::power::*` equivalents as in Step 7.

- [ ] **Step 10: Build**

```bash
/Users/stephenoliver/.platformio/penv/bin/pio run
```

Expected: `SUCCESS`.

- [ ] **Step 11: Flash + smoke test**

```bash
/Users/stephenoliver/.platformio/penv/bin/pio run -t upload
```

Smoke test sequence:
1. Device boots and backlight comes on (LDO2 + brightness).
2. Settings → brightness cycles from dim to bright.
3. A-tap → INFO screen. Check battery voltage, current, bus voltage, and temperature are sensible (nonzero on-battery; vBus > 4000 mV on USB).
4. Hold the AXP side button briefly to enter sleep — screen dims/turns off (`setLcdPower(false)`); wake by short-pressing again — screen comes back (`setLcdPower(true)`).

- [ ] **Step 12: Commit**

```bash
git add src/main.cpp src/xfer.h
git commit -m "Migrate power callers to hal::power"
```

---

## Task 5 — A.2.4: Migrate `imu` callers

**Goal:** Replace `M5.Imu.getAccelData` with `hal::imu::readAccel`. Two call sites.

**Files:**
- Modify: `src/main.cpp`

**Call sites** (grep `M5\.Imu`):
- `main.cpp:93` — the inline accel read (pose-detection call).
- `main.cpp:366` — in `clockUpdateOrient`.
- `main.cpp:494` — another pose read (nap detection).
- `main.cpp:946` — `M5.Imu.Init()` in `setup()` — **removed** (done inside `hal::begin()` eventually, but for now add a direct `hal::begin()`-style init).

- [ ] **Step 1: Add include in `main.cpp`**

```cpp
#include "hal/imu.h"
```

- [ ] **Step 2: Replace every `M5.Imu.getAccelData(&ax, &ay, &az)` call**

Each call has the same signature. Replace each:

```cpp
M5.Imu.getAccelData(&ax, &ay, &az);
```

with:

```cpp
hal::imu::readAccel(ax, ay, az);
```

Grep first to get the count — `grep -n "M5.Imu.getAccelData" src/main.cpp` — and replace all.

- [ ] **Step 3: Remove `M5.Imu.Init()` from `setup()`**

Find:

```cpp
M5.Imu.Init();
```

Delete. The init will migrate into `hal::begin()` at Task 8. For this interim step, that's acceptable — `M5.begin()` in `setup()` (still present) initializes the IMU hardware at a basic level, and our subsequent `hal::imu::readAccel()` calls work because `M5.Imu` is backed by the same hardware.

**Safety check:** if the board shows garbled accel values post-flash, it means `M5.Imu.Init()` was required. Re-add `hal::imu::readAccel()` does not call `M5.Imu.Init()` for us. If this happens, add a stub `hal::imu::begin()` that calls `M5.Imu.Init()` and call it from `setup()` explicitly, in parallel with `hal::beep::begin()`. If values look fine, leave it.

- [ ] **Step 4: Build**

```bash
/Users/stephenoliver/.platformio/penv/bin/pio run
```

Expected: `SUCCESS`.

- [ ] **Step 5: Flash + smoke test**

```bash
/Users/stephenoliver/.platformio/penv/bin/pio run -t upload
```

Smoke test:
1. Face the device down on a flat surface → character goes to sleep (nap mode activates).
2. Flip right-side up → character wakes up.
3. Tilt on its side for a few seconds → (clock landscape logic would activate, but clock is disabled; no visible result, but also no crash).

If nap/wake works correctly, IMU is functional.

- [ ] **Step 6: Commit**

```bash
git add src/main.cpp
git commit -m "Migrate imu callers to hal::imu"
```

---

## Task 6 — A.2.5: Migrate `buttons` callers

**Goal:** Replace `M5.BtnA.*`, `M5.BtnB.*`, and `M5.Axp.GetBtnPress()` with `hal::buttons::*`.

**Files:**
- Modify: `src/main.cpp`

**Call sites** (grep `M5\.Btn` and `GetBtnPress`):

| Current | Replacement |
|---|---|
| `M5.BtnA.isPressed()` | `hal::buttons::pressedA()` |
| `M5.BtnB.isPressed()` | `hal::buttons::pressedB()` |
| `M5.BtnA.pressedFor(ms)` | `hal::buttons::heldA(ms)` |
| `M5.Axp.GetBtnPress() == 0x02` | `hal::buttons::powerButtonPressed()` |

- [ ] **Step 1: Add include**

```cpp
#include "hal/buttons.h"
```

- [ ] **Step 2: Replace all four patterns**

Use grep to enumerate each pattern before replacing. There are several call sites for `BtnA.isPressed()` and `BtnB.isPressed()` in the main input loop, and one `BtnA.pressedFor(600)` for hold-to-menu.

Also look at `wake()`-path code that checks button state to "swallow" first-press-on-wake. The `swallowBtnA` / `swallowBtnB` flags stay in `main.cpp`; only the underlying `BtnA.isPressed()` reads change.

- [ ] **Step 3: Build**

```bash
/Users/stephenoliver/.platformio/penv/bin/pio run
```

Expected: `SUCCESS`.

- [ ] **Step 4: Flash + smoke test**

```bash
/Users/stephenoliver/.platformio/penv/bin/pio run -t upload
```

Smoke test:
1. A-tap cycles NORMAL → INFO → PET → NORMAL.
2. B cycles stats pages on the PET screen.
3. Hold A for ~600ms → menu opens.
4. Navigate menu with A/B, select an item.
5. Short-press AXP side button while awake → screen goes off.
6. Short-press AXP side button while screen off → wakes, first button press after wake is swallowed (test by pressing A immediately on wake; display mode should NOT cycle on that first press).

- [ ] **Step 5: Commit**

```bash
git add src/main.cpp
git commit -m "Migrate button callers to hal::buttons"
```

---

## Task 7 — A.2.6: Migrate `display` callers (move the sprite)

**Goal:** Move `TFT_eSprite spr` ownership from `main.cpp` into `hal/display.cpp`. Every `spr.xxx()` call in `main.cpp` becomes a call on `hal::display::sprite()`. Every `M5.Lcd.xxx()` becomes `hal::display::lcd().xxx()` (for the landscape clock and passkey paths). `pushSprite(0, 0)` becomes `hal::display::push()`. `setRotation` becomes `hal::display::setRotation(r)`.

**This is the biggest migration — touches ~100+ lines across main.cpp, character.cpp, buddy.cpp.**

**Files:**
- Modify: `src/hal/display.cpp` (take ownership of `spr`)
- Modify: `src/main.cpp` (remove global `spr`, replace all call sites)
- Modify: `src/character.cpp` (update `extern TFT_eSprite spr;` and the `_tgt` initialization)
- Modify: `src/buddy.cpp` (same)

- [ ] **Step 1: Move `spr` ownership into `hal/display.cpp`**

Current `hal/display.cpp` has:

```cpp
extern TFT_eSprite spr;  // still lives in main.cpp during A.1..A.2.5
```

Replace that line with ownership + real init:

```cpp
static TFT_eSprite _spr(&M5.Lcd);
```

And update `sprite()`:

```cpp
TFT_eSprite& sprite() { return _spr; }
```

And implement `begin()` to do the createSprite that currently happens in main.cpp's setup():

```cpp
void begin() {
  M5.Lcd.setRotation(0);
  _spr.setColorDepth(8);
  _spr.createSprite(width(), height());
  _spr.setSwapBytes(true);
}
```

(If the actual init in main.cpp's setup() does something different — e.g., a different color depth, no `setSwapBytes` — read `main.cpp` setup() carefully and copy exactly.)

- [ ] **Step 2: Remove `spr` global from `main.cpp`**

Delete the line near the top of `main.cpp`:

```cpp
TFT_eSprite spr = TFT_eSprite(&M5.Lcd);
```

Also delete the block in `setup()` that does `spr.setColorDepth(8); spr.createSprite(W, H); spr.setSwapBytes(true);` (it now lives in `hal::display::begin()`).

- [ ] **Step 3: Add a short reference alias at main.cpp's top**

For minimal call-site churn, keep using the name `spr` in main.cpp by making it a reference to the HAL's sprite:

Near the top of `main.cpp`, after includes:

```cpp
#include "hal/display.h"
static TFT_eSprite& spr = hal::display::sprite();
```

This preserves every existing `spr.xxx()` call site without rewriting them, at no runtime cost.

- [ ] **Step 4: Update `character.cpp`**

Current line 7:

```cpp
extern TFT_eSprite spr;
```

Delete that. Then find line ~47:

```cpp
static TFT_eSPI*   _tgt = &spr;
```

Replace with:

```cpp
static TFT_eSPI*   _tgt = nullptr;
```

And initialize it at the top of `characterInit()`:

```cpp
_tgt = &hal::display::sprite();
```

Add the include at the top:

```cpp
#include "hal/display.h"
```

Also update the direct `spr.xxx()` use at line ~117 (`if (peekMode) { ... spr.xxx ... }`). Replace any `spr.` references with `hal::display::sprite().`.

Use grep: `grep -n "\bspr\b" src/character.cpp`.

- [ ] **Step 5: Update `buddy.cpp`**

Same treatment as character.cpp. Line 6's `extern TFT_eSprite spr;` deletion, line 36's `_tgt = &spr;` → `_tgt = nullptr;` with init done in `buddyInit` or at first tick. Grep for `\bspr\b` and replace with `hal::display::sprite()`.

- [ ] **Step 6: Replace `M5.Lcd.*` calls in `main.cpp`**

Every `M5.Lcd.` becomes `hal::display::lcd().`. Use grep to enumerate (`grep -n "M5\.Lcd" src/main.cpp`). Examples:

```cpp
M5.Lcd.setRotation(0);       →  hal::display::setRotation(0);
M5.Lcd.setRotation(clockOrient); → hal::display::setRotation(clockOrient);
M5.Lcd.fillScreen(p.bg);     →  hal::display::lcd().fillScreen(p.bg);
M5.Lcd.setTextDatum(...);    →  hal::display::lcd().setTextDatum(...);
M5.Lcd.setTextSize(3);       →  hal::display::lcd().setTextSize(3);
M5.Lcd.drawString(hm, ...);  →  hal::display::lcd().drawString(hm, ...);
```

Note: `setRotation` gets a dedicated HAL function; everything else uses `lcd()`.

- [ ] **Step 7: Replace `spr.pushSprite(0, 0)` with `hal::display::push()`**

Grep `pushSprite`. Each occurrence becomes `hal::display::push();`.

- [ ] **Step 8: Remove `M5.begin()` and `M5.Lcd.setRotation(0)` from `setup()`**

Wait — `M5.begin()` is the root init; `hal::begin()` depends on it. Task 8 (below) handles the transition. For **this** task (Task 7), leave `M5.begin()` in setup() as-is. It stays until Task 8 replaces it with `hal::begin()`.

The `M5.Lcd.setRotation(0)` in setup() should still happen — it's now inside `hal::display::begin()`. Add a direct call to `hal::display::begin();` in setup() *right after* the `M5.begin();` call (it requires M5 to be initialized to work).

Order in setup():

```cpp
M5.begin();                    // still here
hal::display::begin();         // new - creates sprite, sets rotation
hal::beep::begin();            // still here from Task 2
// ... rest of setup
```

- [ ] **Step 9: Build**

```bash
/Users/stephenoliver/.platformio/penv/bin/pio run
```

Expected: `SUCCESS`. Likely errors:
- Missed `spr.` or `M5.Lcd.` reference → grep again.
- `_tgt = nullptr;` before use → verify `characterInit` sets it before first `characterTick` call.

- [ ] **Step 10: Flash + full smoke test**

```bash
/Users/stephenoliver/.platformio/penv/bin/pio run -t upload
```

This is the biggest migration so far; run the full walkthrough:
1. Boot — character renders, animates.
2. A cycles NORMAL → INFO → PET → NORMAL; all screens render correctly.
3. PET screen: mood/fed/energy sprites + grid all render; B cycles pages.
4. Hold A → menu; navigate; open Settings; change brightness (visibly applies); change sound (beeps enabled/disabled).
5. Face down → nap (sprite disappears, screen stays on briefly then blanks; wakes on button).
6. BLE pairing (if not already bonded): passkey screen renders.
7. Approval: if a prompt arrives, approval UI renders correctly.

If any screen is blank or garbled: the sprite move is the likely culprit. Check `_spr.createSprite()` ran (add a `Serial.println` to `hal::display::begin()` temporarily if needed).

- [ ] **Step 11: Verify the code-level invariant**

```bash
grep -rn "M5\." src/ --exclude-dir=hal | grep -v "^Binary"
```

Expected: zero matches. Every remaining `M5.` reference should be inside `src/hal/`.

- [ ] **Step 12: Commit**

```bash
git add src/hal/display.cpp src/main.cpp src/character.cpp src/buddy.cpp
git commit -m "Move TFT_eSprite spr into hal::display; migrate display callers"
```

---

## Task 8 — Wire `hal::begin()` / `hal::tick()`

**Goal:** Replace the remaining `M5.begin()` in setup() and `M5.update()` in loop() with `hal::begin()` and `hal::tick()`. After this task, `main.cpp` has zero direct `M5.` references.

**Files:**
- Modify: `src/main.cpp`

- [ ] **Step 1: Verify `hal::begin()` does everything setup currently does**

Check `hal/hal.cpp`'s `begin()` body. It should call, in order: `M5.begin()`, `display::begin()`, `M5.Imu.Init()` (re-add if it was removed in Task 5), and `beep::begin()`.

If Task 5 removed `M5.Imu.Init()` with no replacement, add a `hal::imu::begin()` (trivial wrapper) and call it from `hal::begin()`:

```cpp
// hal/imu.h — add:
void begin();

// hal/imu.cpp — add:
void begin() { M5.Imu.Init(); }

// hal/hal.cpp — add the call:
void begin() {
  M5.begin();
  display::begin();
  imu::begin();
  beep::begin();
}
```

- [ ] **Step 2: Replace `M5.begin()` + individual hal inits in `setup()`**

In `main.cpp` `setup()`, replace the sequence:

```cpp
M5.begin();
hal::display::begin();
hal::beep::begin();
```

with a single call:

```cpp
hal::begin();
```

- [ ] **Step 3: Replace `M5.update()` in `loop()`**

Find:

```cpp
M5.update();
hal::beep::tick();
```

Replace with:

```cpp
hal::tick();
```

(`hal::tick()` already calls both.)

- [ ] **Step 4: Build**

```bash
/Users/stephenoliver/.platformio/penv/bin/pio run
```

Expected: `SUCCESS`.

- [ ] **Step 5: Flash + smoke test**

```bash
/Users/stephenoliver/.platformio/penv/bin/pio run -t upload
```

Smoke test: full device walkthrough — if boot works and buttons respond, `hal::begin` + `hal::tick` are correct. All previously-verified flows (A.2.1 through A.2.5) should still pass.

- [ ] **Step 6: Verify invariant**

```bash
grep -rn "M5\." src/ --exclude-dir=hal
```

Expected: zero matches.

- [ ] **Step 7: Commit**

```bash
git add src/main.cpp src/hal/hal.cpp src/hal/hal.h src/hal/imu.cpp src/hal/imu.h
git commit -m "Wire hal::begin/tick; remove last M5 references from main.cpp"
```

---

## Task 9 — A.3.1: Extract `passkey` screen

**Goal:** Move the passkey display function into its own module.

**Files:**
- Create: `src/screens/passkey.h`
- Create: `src/screens/passkey.cpp`
- Modify: `src/main.cpp`

- [ ] **Step 1: Create `src/screens/passkey.h`**

```cpp
#pragma once

namespace screen { namespace passkey {
  void draw();
}}
```

- [ ] **Step 2: Create `src/screens/passkey.cpp`**

```cpp
#include "passkey.h"
#include "../hal/display.h"
#include "../ble_bridge.h"
#include "../character.h"
#include <TFT_eSPI.h>
#include <stdio.h>

namespace screen { namespace passkey {

void draw() {
  auto& spr = hal::display::sprite();
  const Palette& p = characterPalette();
  // -- PASTE the existing drawPasskey() body from main.cpp here verbatim --
  // It currently starts at roughly main.cpp:518. Copy the body, not the signature.
}

}}
```

Open `src/main.cpp`, find `void drawPasskey() { ... }` around line 518, copy the body (everything between `{` and `}`), paste into the `draw()` body above. Adjust any internal references (there shouldn't be any — it uses `spr`, palette, and `blePasskey()`).

- [ ] **Step 3: Delete `drawPasskey()` from `main.cpp`**

Delete the `drawPasskey` function definition. Keep any forward declarations at the top of main.cpp for now (they'll be cleaned up in A.5).

- [ ] **Step 4: Update call site in `main.cpp`**

Find the call `drawPasskey();` (there's probably one place around line 1221):

```cpp
if (blePasskey()) drawPasskey();
```

Replace:

```cpp
if (blePasskey()) screen::passkey::draw();
```

- [ ] **Step 5: Add include at top of `main.cpp`**

```cpp
#include "screens/passkey.h"
```

- [ ] **Step 6: Build**

```bash
/Users/stephenoliver/.platformio/penv/bin/pio run
```

Expected: `SUCCESS`. If it fails on undefined `spr`, `blePasskey`, or `characterPalette`, the screen's includes are incomplete — add them to `screens/passkey.cpp`.

- [ ] **Step 7: Flash + smoke test**

```bash
/Users/stephenoliver/.platformio/penv/bin/pio run -t upload
```

Smoke test: requires an un-bonded BLE pairing. Either clear bonds on the desktop side (forget the device in System Bluetooth) or add a temporary `bleClearBonds()` call to setup() for one boot. Then re-pair. The 6-digit passkey should render identically to before.

If you can't easily trigger a fresh pair, at minimum verify the device still boots, normal screens render, and no crash.

- [ ] **Step 8: Commit**

```bash
git add src/screens/passkey.h src/screens/passkey.cpp src/main.cpp
git commit -m "Extract passkey screen into src/screens/passkey"
```

---

## Task 10 — A.3.2: Extract `info` screen

**Files:**
- Create: `src/screens/info.h` + `.cpp`
- Modify: `src/main.cpp`

- [ ] **Step 1: Create `src/screens/info.h`**

```cpp
#pragma once

namespace screen { namespace info {
  void draw();
}}
```

- [ ] **Step 2: Create `src/screens/info.cpp`**

```cpp
#include "info.h"
#include "../hal/display.h"
#include "../hal/power.h"
#include "../character.h"
// Whatever other includes drawInfo() uses — check main.cpp around line 532.

namespace screen { namespace info {

void draw() {
  // -- PASTE the body of drawInfo() from main.cpp (starts ~line 532) --
}

}}
```

Move any `ln(...)`-style local helpers used only by `drawInfo` into `info.cpp` as file-scope statics.

- [ ] **Step 3: Delete `drawInfo()` from `main.cpp`**

- [ ] **Step 4: Update call site in `main.cpp`**

Find:

```cpp
else if (displayMode == DISP_INFO) drawInfo();
```

Replace:

```cpp
else if (displayMode == DISP_INFO) screen::info::draw();
```

- [ ] **Step 5: Add include**

```cpp
#include "screens/info.h"
```

- [ ] **Step 6: Build**

```bash
/Users/stephenoliver/.platformio/penv/bin/pio run
```

- [ ] **Step 7: Flash + smoke test**

A-tap to cycle to INFO screen. Verify all lines render (battery V/I, bus V, temperature, MAC, heap, etc.). Values should match pre-change.

- [ ] **Step 8: Commit**

```bash
git add src/screens/info.h src/screens/info.cpp src/main.cpp
git commit -m "Extract info screen"
```

---

## Task 11 — A.3.3: Extract `hud` screen

**Goal:** Move the HUD drawing code and its local state (`msgScroll`, `lastLineGen`) into its own module.

**Files:**
- Create: `src/screens/hud.h` + `.cpp`
- Modify: `src/main.cpp`

- [ ] **Step 1: Create `src/screens/hud.h`**

```cpp
#pragma once

namespace screen { namespace hud {
  void draw();
}}
```

- [ ] **Step 2: Create `src/screens/hud.cpp`**

Include what `drawHUD` uses, then move:

```cpp
#include "hud.h"
#include "../hal/display.h"
#include "../character.h"
// ... any globals drawHUD reads (tama, settings, stats)

namespace screen { namespace hud {

// File-scope state previously living in main.cpp:
static int      msgScroll    = 0;
static uint32_t lastLineGen  = 0;

void draw() {
  // -- PASTE drawHUD() body from main.cpp (~line 890) --
}

}}
```

The body also references `drawApproval()` via `if (tama.promptId[0]) { drawApproval(); return; }`. Leave that call — after Task 12 the approval is its own screen; for now, the existing `drawApproval` function is still in main.cpp, and main.cpp's call site chain dispatches to it. Restructure: in `hud::draw`, move that `if` **out** and let main.cpp's caller do the check (the HUD should draw unconditionally; the caller decides whether to draw HUD or approval).

Actual HUD body (without the approval shortcut):

```cpp
void draw() {
  const Palette& p = characterPalette();
  const int SHOW = 3, LH = 8, WIDTH = 21;
  const int AREA = SHOW * LH + 4;
  auto& spr = hal::display::sprite();
  spr.fillRect(0, hal::display::height() - AREA, hal::display::width(), AREA, p.bg);
  spr.setTextSize(1);
  // ... rest of the original drawHUD body below the first fillRect
}
```

- [ ] **Step 3: Delete `drawHUD()` from `main.cpp`**, along with the `msgScroll` and `lastLineGen` statics (now in hud.cpp).

- [ ] **Step 4: Update main.cpp's call site**

Find the existing call like:

```cpp
else if (settings().hud) drawHUD();
```

Change to:

```cpp
else if (settings().hud) {
  if (tama.promptId[0]) drawApproval();
  else                  screen::hud::draw();
}
```

This extracts the approval-takeover decision up to the caller. **Verify** nothing else in main.cpp now relies on `drawHUD()` redirecting to `drawApproval()` — it shouldn't, but grep.

- [ ] **Step 5: Add include in main.cpp**

```cpp
#include "screens/hud.h"
```

- [ ] **Step 6: Build + flash + smoke test**

```bash
/Users/stephenoliver/.platformio/penv/bin/pio run -t upload
```

Smoke test: during a Claude session, message lines should scroll in the bottom HUD area. Approval prompts should still trigger the approval screen (the new top-level check).

- [ ] **Step 7: Commit**

```bash
git add src/screens/hud.h src/screens/hud.cpp src/main.cpp
git commit -m "Extract hud screen"
```

---

## Task 12 — A.3.4: Extract `approval` screen

**Files:**
- Create: `src/screens/approval.h` + `.cpp`
- Modify: `src/main.cpp`

- [ ] **Step 1: Create `src/screens/approval.h`**

```cpp
#pragma once

namespace screen { namespace approval {
  void draw();
}}
```

- [ ] **Step 2: Create `src/screens/approval.cpp`**

```cpp
#include "approval.h"
#include "../hal/display.h"
#include "../character.h"
// any other includes drawApproval() uses (stats/tama etc.)

namespace screen { namespace approval {

void draw() {
  // -- PASTE drawApproval() body from main.cpp (~line 725) --
}

}}
```

- [ ] **Step 3: Delete `drawApproval()` from `main.cpp`**

- [ ] **Step 4: Update the two call sites in `main.cpp`**

(a) The HUD-promoted check from Task 11:

```cpp
if (tama.promptId[0]) drawApproval();
```

becomes:

```cpp
if (tama.promptId[0]) screen::approval::draw();
```

(b) Any other direct call to `drawApproval()` — grep to make sure nothing else invokes it.

- [ ] **Step 5: Add include in main.cpp**

```cpp
#include "screens/approval.h"
```

- [ ] **Step 6: Build + flash + smoke test**

Wait for or trigger a Claude approval prompt. Approval screen should render; A approves, B denies; beeps fire; stats (APR/DNY) update.

- [ ] **Step 7: Commit**

```bash
git add src/screens/approval.h src/screens/approval.cpp src/main.cpp
git commit -m "Extract approval screen"
```

---

## Task 13 — A.3.5: Extract `clock` screen

**Goal:** Move the clock-rendering code (`drawClock` + its `clockDow` helper + `lastSec`/`paintedOrient` statics) into its own module. Orientation *detection* (`clockUpdateOrient`, `clockRefreshRtc`, the `clockOrient` state) remains in `main.cpp` because it's cross-cutting (IMU + RTC + display-mode + power state).

**Files:**
- Create: `src/screens/clock.h` + `.cpp`
- Modify: `src/main.cpp`

- [ ] **Step 1: Create `src/screens/clock.h`**

```cpp
#pragma once
#include <stdint.h>

namespace screen { namespace clock {
  // orient: 0 = portrait (sprite), 1 or 3 = landscape (direct to LCD)
  void draw(uint8_t orient);
}}
```

- [ ] **Step 2: Create `src/screens/clock.cpp`**

```cpp
#include "clock.h"
#include "../hal/display.h"
#include "../hal/rtc.h"
#include "../character.h"
// any other includes the original drawClock uses

namespace screen { namespace clock {

static uint8_t paintedOrient = 0;
static uint8_t lastSec       = 0xFF;

// Local helper that was in main.cpp; keep its existing body.
static uint8_t dow(const hal::rtc::Date& d) { return d.weekday % 7; }

void draw(uint8_t orient) {
  // -- PASTE drawClock() body from main.cpp (~line 412) --
  // Adjust any reference to `_clkDt` / `_clkTm` — those still live in main.cpp.
  // Easiest: take them as parameters.
}

}}
```

Because `_clkDt` / `_clkTm` live in main.cpp (they're shared with mood logic, not owned by the clock screen), pass them in. Update the header:

```cpp
// clock.h
#include "../hal/rtc.h"
namespace screen { namespace clock {
  void draw(uint8_t orient,
            const hal::rtc::Time& t,
            const hal::rtc::Date& d);
}}
```

And update `draw()` body to reference `t` / `d` instead of `_clkTm` / `_clkDt`.

- [ ] **Step 3: Delete `drawClock()`, `clockDow()`, `paintedOrient`, `lastSec` from `main.cpp`**

Keep `clockUpdateOrient`, `clockRefreshRtc`, `clockOrient`, `orientFrames`, `swapFrames` — those stay in main.cpp.

- [ ] **Step 4: Update main.cpp's call sites**

Grep for `drawClock()`. There are two call sites (portrait and landscape). Replace:

```cpp
drawClock();
```

with:

```cpp
screen::clock::draw(clockOrient, _clkTm, _clkDt);
```

- [ ] **Step 5: Add include in main.cpp**

```cpp
#include "screens/clock.h"
```

- [ ] **Step 6: Build + flash**

Clock mode is currently hard-disabled (`clocking = false`), so there's no visible clock. Just verify the device still boots, all non-clock screens work, no crashes. If someone later re-enables clocking, the call path works.

- [ ] **Step 7: Commit**

```bash
git add src/screens/clock.h src/screens/clock.cpp src/main.cpp
git commit -m "Extract clock screen"
```

---

## Task 14 — A.3.6: Extract `stats` screen

**Goal:** Move `drawPet`, `drawPetStats`, `drawPetHowTo`, the `tinyHeart` helper, and the `petPage` state into `src/screens/stats.cpp`. This is the largest screen extraction.

**Files:**
- Create: `src/screens/stats.h` + `.cpp`
- Modify: `src/main.cpp`

**Naming:** the project already has a `src/stats.h` (data layer). To avoid confusion, this screen uses the namespace `screen::petstats` but file names `stats.h` / `stats.cpp` (inside `src/screens/`, no collision with `src/stats.h`).

- [ ] **Step 1: Create `src/screens/stats.h`**

```cpp
#pragma once
#include <stdint.h>

namespace screen { namespace petstats {
  void    draw();
  void    nextPage();               // called when user presses B
  uint8_t currentPage();            // 0..(PET_PAGES-1)
}}
```

- [ ] **Step 2: Create `src/screens/stats.cpp`**

```cpp
#include "stats.h"
#include "../hal/display.h"
#include "../character.h"
#include "../stats.h"       // project data stats (different dir, no collision)
#include <stdio.h>

namespace screen { namespace petstats {

static constexpr uint8_t PET_PAGES = 2;
static uint8_t petPage = 0;

uint8_t currentPage() { return petPage; }
void    nextPage()    { petPage = (petPage + 1) % PET_PAGES; }

// tinyHeart moves here as a file-scope static.
static void tinyHeart(int x, int y, bool filled, uint16_t col) {
  // -- PASTE tinyHeart body from main.cpp --
}

static void drawPetStats(const Palette& p) {
  // -- PASTE drawPetStats() body from main.cpp --
}

static void drawPetHowTo(const Palette& p) {
  // -- PASTE drawPetHowTo() body from main.cpp --
}

void draw() {
  const Palette& p = characterPalette();
  if (petPage == 0) drawPetStats(p);
  else              drawPetHowTo(p);
}

}}
```

- [ ] **Step 3: Delete from `main.cpp`**

Delete: `drawPet()`, `drawPetStats()`, `drawPetHowTo()`, `tinyHeart()`, `static uint8_t petPage`, `static constexpr uint8_t PET_PAGES` (if it's in main.cpp).

- [ ] **Step 4: Update call sites in `main.cpp`**

- Any `drawPet()` call →  `screen::petstats::draw()`
- Any B-button-on-pet logic that did `petPage = (petPage + 1) % PET_PAGES;` → `screen::petstats::nextPage();`

- [ ] **Step 5: Add include**

```cpp
#include "screens/stats.h"
```

- [ ] **Step 6: Build + flash**

```bash
/Users/stephenoliver/.platformio/penv/bin/pio run -t upload
```

**Critical smoke test:** this screen holds the recently-tuned layout. Verify:
1. A-tap to PET screen.
2. Mood hearts (4, evenly spaced across top), fed dots (10, evenly spaced), energy bars (5, evenly spaced) all render.
3. Grid below: APR / DNY row, TDY / NAP row, then full-width TOK row.
4. TOK formats correctly: values like `800`, `1.6K`, `400K`, `1.5M` depending on count.
5. B-press cycles to how-to page; B again returns.

Per acceptance criterion (b): minor 1-2 px shifts OK. No feature regressions.

- [ ] **Step 7: Commit**

```bash
git add src/screens/stats.h src/screens/stats.cpp src/main.cpp
git commit -m "Extract pet stats screen"
```

---

## Task 15 — A.3.7: Extract `menu`, `settings`, `reset` screens

**Goal:** Three related screens, extracted together. They own their selected-index / confirm state.

**Files:**
- Create: `src/screens/menu.h` + `.cpp`, `src/screens/settings.h` + `.cpp`, `src/screens/reset.h` + `.cpp`
- Modify: `src/main.cpp`

- [ ] **Step 1: Create each screen as `draw()` only** (input migration happens in Task 17).

Template for each (adapt names):

```cpp
// screens/menu.h
#pragma once

namespace screen { namespace menu {
  void draw();
  uint8_t  selected();                  // current highlighted index
  void     setSelected(uint8_t i);
  uint8_t  itemCount();                 // so main.cpp can wrap nav
}}
```

Same shape for `settings` and `reset`. `reset` probably needs a `bool confirming()` accessor and a `setConfirming(bool)`.

In each `.cpp`, move:
- The draw function body (`drawMenu`, `drawSettings`, `drawReset`).
- The file-scope selected-index / confirm-state static from main.cpp.
- Any item-list arrays (e.g., `menuItems[]`, `settingsItems[]`) used only by that screen.

- [ ] **Step 2: Delete the moved code from `main.cpp`**

The draw functions and the static state variables. Keep the button-handling switch/cases that call them — main.cpp still routes input until Task 17.

- [ ] **Step 3: Update call sites**

```cpp
if (resetOpen) drawReset();
else if (settingsOpen) drawSettings();
else if (menuOpen) drawMenu();
```

becomes:

```cpp
if (resetOpen) screen::reset::draw();
else if (settingsOpen) screen::settings::draw();
else if (menuOpen) screen::menu::draw();
```

And anywhere main.cpp manipulates `menuSel`, `settingsSel`, `resetConfirm`, etc., switch to the accessor/setter APIs.

- [ ] **Step 4: Add includes**

```cpp
#include "screens/menu.h"
#include "screens/settings.h"
#include "screens/reset.h"
```

- [ ] **Step 5: Build + flash + smoke test**

```bash
/Users/stephenoliver/.platformio/penv/bin/pio run -t upload
```

Smoke test:
1. Hold A → menu opens; A/B navigate; selection works.
2. Menu → Settings; navigate; change an item (e.g., sound off/on, cycle brightness); Back returns to menu.
3. Menu → Reset; confirm dialog appears; A confirms (clears NVS **— careful, this wipes settings**; either accept or test by cancelling instead), B cancels.

**Safety:** if you don't want to actually reset, just verify the confirm dialog renders correctly and cancel.

- [ ] **Step 6: Commit**

```bash
git add src/screens/menu.h src/screens/menu.cpp \
        src/screens/settings.h src/screens/settings.cpp \
        src/screens/reset.h src/screens/reset.cpp \
        src/main.cpp
git commit -m "Extract menu, settings, reset screens"
```

---

## Task 16 — A.4: Input events + screen input handlers

**Goal:** Introduce `Button` / `ButtonEvent` enums in `src/input.h`. Add synthesis in main.cpp (raw hal::buttons polling → event stream). Add `handleButton` entry points to interactive screens and route events to them.

**Files:**
- Create: `src/input.h`
- Modify: `src/main.cpp`
- Modify: `src/screens/stats.h` + `.cpp`, `src/screens/menu.h` + `.cpp`, `src/screens/settings.h` + `.cpp`, `src/screens/reset.h` + `.cpp`, `src/screens/approval.h` + `.cpp`

- [ ] **Step 1: Create `src/input.h`**

```cpp
#pragma once

enum class Button       { A, B, Power };
enum class ButtonEvent  { Tap, LongPress, Release };
```

- [ ] **Step 2: Add event-synthesis code in `main.cpp`**

Add a small function that, each frame, reads `hal::buttons::*` and emits events, handling tap-vs-long-press timing. Preserve the existing `swallowBtnA` / `swallowBtnB` behavior (suppress first event after wake).

Suggested skeleton — full implementation depends on the current timing logic in main.cpp; preserve its behavior:

```cpp
// Somewhere near the top of main.cpp
#include "input.h"

struct BtnState {
  bool prev = false;
  uint32_t pressedAt = 0;
  bool longFired = false;
};
static BtnState btnAState, btnBState, btnPowerState;

// Returns the next event, or nullopt-equivalent (signaled by a bool in params).
// Or: a vector of events per frame. Simplest: emit to a callback.
static void pollInput(void (*emit)(Button, ButtonEvent)) {
  uint32_t now = millis();
  // ... existing tap/hold logic, but calling emit(Button::A, ButtonEvent::Tap) etc.
}
```

Or simpler — a small event queue inline in the loop body:

```cpp
// Each frame:
bool aNow = hal::buttons::pressedA();
bool bNow = hal::buttons::pressedB();
// Emit Tap on rising-edge + released-before-longpress-threshold;
// Emit LongPress when heldA(600) returns true and longFired==false.
// Track state with the static BtnState vars above.
```

Use the existing main.cpp tap/hold code as the reference — extract it into this synthesizer and emit events instead of directly calling action handlers.

- [ ] **Step 3: Add `handleButton` to each interactive screen**

Header example:

```cpp
// screens/menu.h
#include "../input.h"

namespace screen { namespace menu {
  void draw();
  bool handleButton(Button b, ButtonEvent e);  // true if consumed
  // ... accessors
}}
```

Implementation example:

```cpp
// screens/menu.cpp
bool handleButton(Button b, ButtonEvent e) {
  if (b == Button::B && e == ButtonEvent::Tap) { nextItem(); return true; }
  if (b == Button::A && e == ButtonEvent::Tap) { activateItem(); return true; }
  // ... whatever the previous menu input code did in main.cpp
  return false;
}
```

Move the relevant `if (M5.BtnA...)`-style branches from main.cpp into each screen's handler, adapted to operate on Button/ButtonEvent.

- [ ] **Step 4: Main loop dispatch**

Replace main.cpp's current inline button-reading with:

```cpp
// each frame
pollInput([](Button b, ButtonEvent e) {
  // Route to active interactive screen first
  bool consumed = false;
  if (resetOpen)          consumed = screen::reset::handleButton(b, e);
  else if (settingsOpen)  consumed = screen::settings::handleButton(b, e);
  else if (menuOpen)      consumed = screen::menu::handleButton(b, e);
  else if (tama.promptId[0]) consumed = screen::approval::handleButton(b, e);
  else if (displayMode == DISP_PET) consumed = screen::petstats::handleButton(b, e);

  if (!consumed) {
    // Global actions: A-tap cycles displayMode, hold-A opens menu, power button sleeps, etc.
    // -- the "fall-through" cases from the current main.cpp input block --
  }
});
```

- [ ] **Step 5: Remove the now-dead inline `if (M5.BtnA.isPressed())` chains** from main.cpp. The old state (`btnALong`, etc.) and the new BtnState statics may overlap — consolidate into the new synthesizer only.

- [ ] **Step 6: Build**

```bash
/Users/stephenoliver/.platformio/penv/bin/pio run
```

Expected: `SUCCESS`. Errors usually indicate a timing variable that's now defined in two places — delete the old one.

- [ ] **Step 7: Flash + full smoke test**

```bash
/Users/stephenoliver/.platformio/penv/bin/pio run -t upload
```

Every button flow needs re-testing:
1. A-tap cycles NORMAL → INFO → PET → NORMAL.
2. B on PET cycles stats pages.
3. Hold A for ~600ms opens menu.
4. In menu: A = select, B = next item.
5. In Settings: same.
6. In Reset dialog: A = confirm, B = cancel.
7. Approval prompt: A = approve, B = deny.
8. First press after wake is swallowed (doesn't cycle displayMode).
9. Power-button tap still sleeps the screen.

Any regression = a mapping error between old inline code and new `handleButton`. Most common: tap-vs-long-press timing or a missed edge case.

- [ ] **Step 8: Commit**

```bash
git add src/input.h src/screens/*.cpp src/screens/*.h src/main.cpp
git commit -m "Add input event synthesis; route buttons through screen::handleButton"
```

---

## Task 17 — A.5: Cleanup pass

**Goal:** Remove dead code, stale comments, and unused includes. No functional changes.

**Files:**
- Modify: `src/main.cpp`
- Possibly: any file that has lingering `extern TFT_eSprite spr;` or unneeded M5 includes

- [ ] **Step 1: Grep for lingering M5 references outside hal/**

```bash
grep -rn "M5\." src/ --exclude-dir=hal
```

Expected output: **empty**. If anything appears, migrate it (shouldn't happen after Task 8; this is a safety net).

- [ ] **Step 2: Grep for `extern TFT_eSprite`**

```bash
grep -rn "extern TFT_eSprite" src/
```

Expected: empty. If character.cpp or buddy.cpp still has the extern, delete the line (they now use `hal::display::sprite()`).

- [ ] **Step 3: Remove `#include <M5StickCPlus.h>` from `main.cpp`**

Main.cpp no longer directly calls M5 APIs. The HAL headers don't transitively include M5StickCPlus.h in their public interface (check: `hal/*.h` should only include minimal types). Remove the include from main.cpp.

If this causes build errors (some type from M5StickCPlus.h is still referenced indirectly), leave the include with a comment explaining why; otherwise, delete it.

- [ ] **Step 4: Remove stale forward declarations in main.cpp**

Look at the top of main.cpp for the block of `void drawXxx();` forward declarations. Every `draw*` function has moved into `screens/*.cpp`. Delete any forward declaration whose implementation no longer lives in main.cpp. Grep confirms (`grep -n "^void draw" src/main.cpp` — there should be zero).

- [ ] **Step 5: Delete stale comments**

Search main.cpp for comments referencing moved code — "Charging clock: takes over the home screen…", "Jump to the approval screen…", etc. — and delete or update them if their content no longer matches what's in the file. Keep comments whose context still applies (orientation detection, nap timer, etc.).

- [ ] **Step 5b: Prune unused screen accessors**

Task 15 added accessors like `screen::menu::selected()`, `setSelected()`, `itemCount()`, `screen::reset::confirming()` for main.cpp to drive the nav. After Task 16's `handleButton` migration, main.cpp no longer calls those accessors — nav lives inside each screen. Grep each accessor:

```bash
grep -rn "screen::menu::selected\|screen::menu::setSelected\|screen::menu::itemCount" src/
grep -rn "screen::settings::selected\|screen::settings::setSelected\|screen::settings::itemCount" src/
grep -rn "screen::reset::confirming\|screen::reset::setConfirming" src/
```

For any accessor with only its own screen's `.cpp` as caller, delete the declaration from the `.h` and the definition from the `.cpp`. Keep any that main.cpp genuinely still needs for transition logic (e.g., knowing the menu is on "exit" item).

- [ ] **Step 6: Verify `main.cpp` line count**

```bash
wc -l src/main.cpp
```

Expected: under 500 lines (was 1265). If it's still over 600, a screen or chunk of HAL wasn't fully extracted — grep for lingering draw/hardware code.

- [ ] **Step 7: Build + final smoke test**

```bash
/Users/stephenoliver/.platformio/penv/bin/pio run -t upload
```

Full feature walkthrough (12 items from the spec's validation section):

1. Boot + character animates.
2. A cycles NORMAL → INFO → PET → NORMAL.
3. PET: indicators + grid + B cycles pages.
4. Long-hold A opens menu; A/B navigate; back returns.
5. Settings: each item changes; persists across reboot.
6. Reset dialog cancel works. (Skip confirm to preserve NVS.)
7. Beeps on prompt arrival, approval, wake, menu nav. Brightness visibly applies.
8. BLE passkey renders on fresh pair.
9. Approval: A approves, B denies; APR/DNY increment; beeps fire.
10. Face-down → nap; wake swallows first press; screen-off timer kicks in; wake restores.
11. HUD message scroll during a Claude session.
12. XFer: drop a character folder via Claude Desktop; progress bar renders; character reloads.

- [ ] **Step 8: Final code-level assertions**

```bash
# Zero M5 references outside hal/
test "$(grep -rn 'M5\.' src/ --exclude-dir=hal | wc -l)" -eq 0 || echo "FAIL: M5 refs leaked"

# Zero extern TFT_eSprite outside hal/
test "$(grep -rn 'extern TFT_eSprite' src/ | wc -l)" -eq 0 || echo "FAIL: extern spr leaked"

# main.cpp under 500 lines
test "$(wc -l < src/main.cpp)" -lt 500 || echo "FAIL: main.cpp too long"
```

All three should print nothing.

- [ ] **Step 9: Commit**

```bash
git add src/
git commit -m "Cleanup: remove stale forward decls, unused includes, moved comments"
```

---

## Completion checklist

After Task 17, verify:

- [ ] `grep -rn "M5\." src/ --exclude-dir=hal` returns zero.
- [ ] `grep -rn "TFT_eSprite spr" src/` matches only `src/hal/display.cpp`.
- [ ] `grep -rn "TFT_eSPI" src/` matches only `hal/`, `character.*`, `buddy.*`.
- [ ] `wc -l src/main.cpp` < 500.
- [ ] All 12 feature flows from the spec's validation section pass manual walkthrough.
- [ ] `git log --oneline` shows ~17 refactor commits, each flashable and functional.

Phase A is complete. Phase B (Core2 support) is a separate spec + plan.
