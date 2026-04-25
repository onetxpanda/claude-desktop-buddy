# Phase B.1 — M5Unified Library Migration — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the `M5StickCPlus` library with `M5Unified` across the entire codebase, swapping display types (`TFT_eSprite`→`M5Canvas`, `TFT_eSPI`→`M5GFX`) and renaming the shared sprite identifier (`spr`→`canvas`), so that Phase B.2 (Core2 support) becomes purely additive.

**Architecture:** One atomic commit. The library swap invalidates every `TFT_eSprite`, `M5.Axp`, `M5.Beep`, and `M5.Rtc` reference simultaneously, so no incremental split compiles without a shim — which the spec explicitly rejects. The HAL's public namespace-function surface stays identical (except for display return types); HAL implementations and all display-type consumers update in lockstep.

**Tech Stack:** PlatformIO, Arduino, ESP32, M5Unified library, M5GFX (LovyanGFX-derived), ESP-IDF BLE.

**Verification model:** No tests, no on-device walkthrough. Acceptance is **build success + grep-based invariants** per the spec. No manual device testing required.

**Spec reference:** `docs/superpowers/specs/2026-04-24-phase-b1-m5unified-migration-design.md`

**Build command:** `/Users/stephenoliver/.platformio/penv/bin/pio run`

---

## Task 1 — Atomic M5Unified migration

One task, many steps, single commit at the end. The tree is NOT buildable between Step 1 and Step 11 — do not attempt `pio run` mid-task. Build verification happens once at Step 12 after every change lands.

**Files modified (~32 total):**
- `platformio.ini`
- `src/hal/display.h`, `display.cpp`
- `src/hal/power.h`, `power.cpp`
- `src/hal/beep.cpp`
- `src/hal/imu.cpp`
- `src/hal/rtc.cpp`
- `src/hal/buttons.cpp`
- `src/hal/hal.cpp`
- `src/main.cpp`
- `src/character.h`, `src/character.cpp`
- `src/buddy.h`, `src/buddy.cpp`
- `src/buddies/*.cpp` (18 files — enumerate with `ls src/buddies/*.cpp`)
- `src/screens/*.cpp` (9 files — enumerate with `ls src/screens/*.cpp`)
- `src/screens/info.cpp` (additionally — drop AXP temperature line)

---

- [ ] **Step 1 — Swap the library in `platformio.ini`**

Read `platformio.ini`. Find the line `    m5stack/M5StickCPlus` under `lib_deps`. Replace it with `    m5stack/M5Unified`.

Final lib_deps block should look like:

```ini
lib_deps =
    m5stack/M5Unified
    bitbank2/AnimatedGIF @ ^2.1.1
    bblanchon/ArduinoJson @ ^7.0.0
```

No other changes to `platformio.ini`.

---

- [ ] **Step 2 — Rewrite `src/hal/display.h`**

Use `Write` to replace file contents:

```cpp
#pragma once
#include <M5Unified.h>

namespace hal { namespace display {
  void begin();                    // creates sprite, sets initial rotation
  M5GFX&       lcd();              // direct LCD (landscape clock, passkey)
  M5Canvas&    sprite();           // shared drawing surface
  int  width();                    // 135 on StickC Plus
  int  height();                   // 240
  void setRotation(uint8_t r);     // 0..3
  void push();                     // sprite → LCD
}}
```

---

- [ ] **Step 3 — Rewrite `src/hal/display.cpp`**

Use `Write` to replace file contents:

```cpp
#include "display.h"
#include <M5Unified.h>

// Sprite owned here. file-scope static — initialized at program startup,
// before main.cpp's reference binds.
static M5Canvas _spr(&M5.Display);

namespace hal { namespace display {

void begin() {
  M5.Display.setRotation(0);
  _spr.createSprite(135, 240);
}

M5GFX&       lcd()           { return M5.Display; }
M5Canvas&    sprite()        { return _spr; }
int  width()                 { return 135; }
int  height()                { return 240; }
void setRotation(uint8_t r)  { M5.Display.setRotation(r); }
void push()                  { _spr.pushSprite(0, 0); }

}}
```

---

- [ ] **Step 4 — Rewrite `src/hal/power.h`**

Remove the `axpTemp()` declaration. Use `Write` to replace file contents:

```cpp
#pragma once
#include <stdint.h>

namespace hal { namespace power {
  float busVoltage();                 // VBus in volts (> 4.0 = USB attached)
  float batVoltage();                 // battery V
  float batCurrent();                 // battery current (mA)
  void  setBrightness(uint8_t level); // 0..4 — preserves Phase A mapping
  void  setLcdPower(bool on);         // Display.wakeup / Display.sleep
  void  powerOff();                   // hard shutdown
}}
```

---

- [ ] **Step 5 — Rewrite `src/hal/power.cpp`**

Use `Write` to replace file contents:

```cpp
#include "power.h"
#include <M5Unified.h>

namespace hal { namespace power {

// M5Unified exposes battery/bus telemetry in millivolts; HAL normalizes to volts
// so existing callers (clock-refresh USB detection, INFO screen) stay unchanged.
float busVoltage() { return M5.Power.getVBUSVoltage() / 1000.0f; }
float batVoltage() { return M5.Power.getBatteryVoltage() / 1000.0f; }
float batCurrent() { return M5.Power.getBatteryCurrent(); }  // already mA

void setBrightness(uint8_t level) {
  // Phase A mapping preserved: level 0..4 → raw 20/40/60/80/100.
  M5.Display.setBrightness(20 + level * 20);
}

void setLcdPower(bool on) {
  if (on) M5.Display.wakeup();
  else    M5.Display.sleep();
}

void powerOff() { M5.Power.powerOff(); }

}}
```

Note: `axpTemp()` is deliberately NOT included.

---

- [ ] **Step 6 — Rewrite `src/hal/beep.cpp`**

Use `Write` to replace file contents:

```cpp
#include "beep.h"
#include <M5Unified.h>

namespace hal { namespace beep {

void begin()                              { /* M5.Speaker.begin() called by M5.begin() */ }
void tick()                               { /* M5.Speaker manages timing internally */ }
void tone(uint16_t freq, uint16_t ms)     { M5.Speaker.tone(freq, ms); }

}}
```

---

- [ ] **Step 7 — Rewrite `src/hal/imu.cpp`**

M5Unified's IMU returns a combined struct; adapt the readAccel signature. Also remove the `#undef imu` workaround (M5Unified doesn't have the macro collision).

Use `Write` to replace file contents:

```cpp
#include "imu.h"
#include <M5Unified.h>

namespace hal { namespace imu {

void begin() { M5.Imu.begin(); }

void readAccel(float& ax, float& ay, float& az) {
  auto d = M5.Imu.getImuData();
  ax = d.accel.x;
  ay = d.accel.y;
  az = d.accel.z;
}

}}
```

---

- [ ] **Step 8 — Rewrite `src/hal/rtc.cpp`**

M5Unified combines time and date into a single `m5::rtc_datetime_t`. Translate to/from the HAL's plain `Time`/`Date` structs.

Use `Write` to replace file contents:

```cpp
#include "rtc.h"
#include <M5Unified.h>

namespace hal { namespace rtc {

void getTime(Time& out) {
  auto dt = M5.Rtc.getDateTime();
  out.h = dt.time.hours;
  out.m = dt.time.minutes;
  out.s = dt.time.seconds;
}

void getDate(Date& out) {
  auto dt = M5.Rtc.getDateTime();
  out.weekday = dt.date.weekDay;
  out.month   = dt.date.month;
  out.day     = dt.date.date;
  out.year    = dt.date.year;
}

void setTime(const Time& in) {
  auto dt = M5.Rtc.getDateTime();
  dt.time.hours   = in.h;
  dt.time.minutes = in.m;
  dt.time.seconds = in.s;
  M5.Rtc.setDateTime(dt);
}

void setDate(const Date& in) {
  auto dt = M5.Rtc.getDateTime();
  dt.date.weekDay = in.weekday;
  dt.date.month   = in.month;
  dt.date.date    = in.day;
  dt.date.year    = in.year;
  M5.Rtc.setDateTime(dt);
}

}}
```

---

- [ ] **Step 9 — Rewrite `src/hal/buttons.cpp`**

Power-button API changes; everything else stays the same.

Use `Write` to replace file contents:

```cpp
#include "buttons.h"
#include <M5Unified.h>

namespace hal { namespace buttons {

bool pressedA()             { return M5.BtnA.isPressed(); }
bool pressedB()             { return M5.BtnB.isPressed(); }
bool heldA(uint16_t ms)     { return M5.BtnA.pressedFor(ms); }
bool wasReleasedA()         { return M5.BtnA.wasReleased(); }
bool wasPressedB()          { return M5.BtnB.wasPressed(); }
bool powerButtonPressed()   { return M5.BtnPWR.wasClicked(); }

}}
```

---

- [ ] **Step 10 — Rewrite `src/hal/hal.cpp`**

Remove the `#undef imu` workaround — M5Unified doesn't define the macro.

Use `Write` to replace file contents:

```cpp
#include "hal.h"
#include "display.h"
#include "beep.h"
#include "imu.h"
#include <M5Unified.h>

namespace hal {

void begin() {
  M5.begin();
  display::begin();
  imu::begin();
  beep::begin();
}

void tick() {
  M5.update();
  beep::tick();
}

} // namespace hal
```

---

- [ ] **Step 11 — Update all `spr` → `canvas` consumers**

This is the bulk of the mechanical work. Every `.cpp` and `.h` that currently has `extern TFT_eSprite& spr;` or uses `spr.xxx()` in its body needs updating. The change pattern is identical across all files:

- `extern TFT_eSprite& spr;` → `extern M5Canvas& canvas;`
- Every `spr.` → `canvas.`
- Any `TFT_eSPI*` function parameter → `M5GFX*` (only in `character.h` / `buddy.h`)
- Any `TFT_eSPI&` reference → `M5GFX&`

**Process each file below individually with Edit/Read tools. Do NOT use shell loops — the permission system rejects `"$f"`-style patterns.**

**Step 11a — `src/main.cpp`:**

1. Read the full file; grep for `spr` and `TFT_eSprite`.
2. Replace `TFT_eSprite& spr = hal::display::sprite();` with `M5Canvas& canvas = hal::display::sprite();`
3. Every other `spr` identifier in the file → `canvas` (use Edit with `replace_all: true` for the most common patterns; handle exceptions individually).
4. `buddyRenderTo(&M5.Lcd, ...)` should already be `buddyRenderTo(&hal::display::lcd(), ...)` — verify; if still `M5.Lcd`, fix. (Phase A's Task 7 should have handled this.)
5. Same for `characterRenderTo(&M5.Lcd, ...)`.
6. Remove the `#undef imu` line (M5Unified doesn't need it).
7. Leave `TamaState tama;` and all other non-display code alone.

**Step 11b — `src/character.h`:**

Read, then Edit. Change the function signatures containing `TFT_eSPI*`:

- `void characterRenderTo(TFT_eSPI* tgt, int cx, int cy);` → `void characterRenderTo(M5GFX* tgt, int cx, int cy);`
- Add `#include <M5Unified.h>` at the top if not already included via another header. If `M5GFX` isn't resolvable without it, add the include.

**Step 11c — `src/character.cpp`:**

Read, then Edit:

- `extern TFT_eSprite& spr;` → `extern M5Canvas& canvas;`
- `static TFT_eSPI* _tgt = nullptr;` (the function-scope render target pointer) → `static M5GFX* _tgt = nullptr;`
- `_tgt = &hal::display::sprite();` — unchanged (type of sprite() is now M5Canvas&, which is-a M5GFX).
  - Actually **wait**: `M5Canvas` inherits from `lgfx::LGFX_Sprite`, which inherits from `lgfx::LGFXBase`. `M5GFX` also inherits from `lgfx::LGFXBase`. They share a base but a `M5Canvas&` may not be directly assignable to `M5GFX*`. If compilation fails here, change `_tgt`'s type to `lgfx::LGFXBase*` and cast appropriately, OR store the sprite as `M5Canvas*` and the LCD as `M5GFX*` in separate pointers — see Step 11 Troubleshooting below.
- `void characterRenderTo(TFT_eSPI* tgt, int cx, int cy)` → `void characterRenderTo(M5GFX* tgt, int cx, int cy)` (matches header).
- Every `spr.xxx()` in function bodies → `canvas.xxx()`.

**Step 11d — `src/buddy.h`:**

Same treatment as character.h:

- `void buddyRenderTo(TFT_eSPI* tgt, uint8_t state);` → `void buddyRenderTo(M5GFX* tgt, uint8_t state);`

**Step 11e — `src/buddy.cpp`:**

Same as character.cpp:

- `extern TFT_eSprite& spr;` → `extern M5Canvas& canvas;`
- `static TFT_eSPI* _tgt = nullptr;` → `static M5GFX* _tgt = nullptr;` (or `LGFXBase*` — see troubleshooting)
- `void buddyRenderTo(TFT_eSPI* tgt, uint8_t state)` → `void buddyRenderTo(M5GFX* tgt, uint8_t state)`
- Every `spr.xxx()` → `canvas.xxx()`

**Step 11f — `src/buddies/*.cpp` (18 files):**

Run `ls src/buddies/*.cpp` to get the exact list. For EACH file individually:

1. Read to see the current state.
2. Edit to replace `extern TFT_eSprite& spr;` with `extern M5Canvas& canvas;`.
3. Edit to replace every `spr.xxx()` with `canvas.xxx()` in bodies (often `replace_all: true` works for a single identifier rename).

**Step 11g — `src/screens/*.cpp` (9 files):**

Run `ls src/screens/*.cpp` to confirm the list. Same per-file treatment as buddies:

1. Read.
2. Edit extern.
3. Edit body references.

Some screens may have `extern TFT_eSprite& spr;` AND pass `spr` to drawing helpers inline. All `spr` → `canvas`.

**Step 11 Troubleshooting — if `_tgt` type-incompatibility errors appear:**

Symptom: `error: cannot convert 'M5Canvas*' to 'M5GFX*'` (or similar) when assigning `&hal::display::sprite()` to `_tgt`.

Fix: change `_tgt`'s declaration to `static lgfx::LGFXBase* _tgt = nullptr;` in both `character.cpp` and `buddy.cpp`. Include `<M5Unified.h>` which transitively provides `lgfx::LGFXBase`. The render-target pointer only needs to call drawing primitives (`drawPixel`, `fillRect`, etc.), all of which are declared on `LGFXBase`. The function parameter type can stay `M5GFX*` for the public API; cast inside the function: `_tgt = tgt;` becomes a widening assignment that compiles cleanly.

---

- [ ] **Step 12 — Drop AXP temperature from the INFO screen**

Read `src/screens/info.cpp`. Find the line that renders the AXP temperature (pattern: a call referencing either `hal::power::axpTemp()` or an M5.Axp.GetTempInAXP192 leftover). Delete the line that prints it (and any label line directly above it that says "temp" or similar).

If the screen module still has any reference to `axpTemp()`, delete that too.

---

- [ ] **Step 13 — Build**

Run:

```bash
/Users/stephenoliver/.platformio/penv/bin/pio run
```

Expected: `SUCCESS`.

**If the build fails**, diagnose by error type:
- Missing `<M5Unified.h>` in a file: add the include at the top.
- `TFT_eSprite` / `TFT_eSPI` still referenced somewhere: `grep -rn "TFT_e" src/` — find the straggler and update.
- `M5.Axp` / `M5.Beep` still referenced: `grep -rn "M5\.Axp\|M5\.Beep\|M5\.Lcd" src/` — update.
- `_tgt` type mismatch in character.cpp / buddy.cpp: see Step 11 Troubleshooting above.
- `hal::power::axpTemp` still called somewhere: grep and delete the caller.

Iterate until SUCCESS.

---

- [ ] **Step 14 — Verify code-level invariants**

All six greps must return zero matches (non-comment lines only):

```bash
grep -rn "TFT_eSprite\|TFT_eSPI" src/
grep -rn "M5\.Axp\|M5\.Beep\|M5\.Lcd" src/
grep -rn "M5StickCPlus" src/ platformio.ini
grep -rn "\bspr\b" src/
grep -rn "#undef imu" src/
grep -rn "axpTemp" src/
```

If any produce matches:
- Comments-only matches are fine (most `grep` hits will be source; check visually).
- Real matches = a file still needs migration. Update it and re-run.

---

- [ ] **Step 15 — Commit**

Only commit once Steps 13 and 14 both pass.

```bash
git add platformio.ini src/
git commit -m "Migrate M5StickCPlus → M5Unified; rename spr → canvas"
```

Verify the commit lands cleanly:

```bash
git log --oneline -3
git status
```

Status should show "nothing to commit, working tree clean".

---

## Completion checklist

After Task 1 completes, verify:

- [ ] `pio run` exits 0.
- [ ] All six invariant greps return zero non-comment matches.
- [ ] One new commit on `hal-refactor` with message `Migrate M5StickCPlus → M5Unified; rename spr → canvas`.
- [ ] `docs/superpowers/specs/2026-04-24-phase-b1-m5unified-migration-design.md` matches what was implemented (no scope drift).

Phase B.1 is complete. Phase B.2 (Core2 HAL addition) is a separate spec + plan.
