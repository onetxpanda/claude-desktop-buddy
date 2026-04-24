# Phase A — Device HAL & Screen Refactor (design)

- **Date**: 2026-04-24
- **Scope**: Refactor only. No new device targets, no Core2 code, no build variants. Firmware still builds one `m5stickc-plus` env and behaves functionally identically.
- **Acceptance criterion**: Functionally equivalent behavior on M5StickC Plus. Minor pixel shifts (1-2px) acceptable if they fall out naturally from extraction; no feature regressions.
- **Out of scope (future Phase B / deferred)**: adding M5Stack Core2 as a second device, per-device layout variants, runtime device selection, automated test harness with mock HAL.

### Deferred: deep-sleep on nap with IMU wake

Considered as part of Phase A scoping; deferred to a future phase to keep the refactor focused.

- **Hardware feasibility (StickC Plus):** MPU6886 INT line is wired to GPIO 35 (RTC-capable, `RTC_GPIO_5`), so `esp_sleep_enable_ext0_wakeup(GPIO_NUM_35, 1)` can wake from deep sleep on motion. The MPU6886 itself supports a motion-detection interrupt via `INT_ENABLE` configuration.
- **Scope estimate:** ~150-300 LoC. Configure IMU interrupt, manage BLE teardown before deep sleep (the bridge connection drops on entry; reconnect handled by Claude Desktop's auto-reconnect path), persist runtime state to NVS or RTC RAM, branch boot path on wake-from-sleep cause, restart character render cleanly.
- **UX trade-offs:** deep sleep drops to ~10 µA but reboots take ~1-2 s and the BLE peer must re-pair the active connection. Light sleep keeps BLE alive but saves only ~30-40 mA; the bigger win is deep sleep.
- **Why deferred:** unrelated to the refactor's separation goals; mixing it in muddies clean per-screen / per-HAL commits. The refactor exposes the right hooks (`hal::power::*`, `hal::imu::*`, the lifecycle in `main.cpp`) so the deep-sleep work becomes additive afterwards.
- **Future task shape:** new spec + plan once Phase A lands. Likely Phase A.6 or its own letter.

## Why

`main.cpp` is 1265 LoC with 47 direct `M5.*` references scattered through lifecycle, state machine, input, power, and ~15 drawing functions that hard-code 135×240 / font-size-1 assumptions. The file is hard to read, hard to review, and — more importantly — would be rewritten wholesale when Core2 arrives.

Goal: isolate device-specific concerns behind clean, narrow seams so that adding Core2 later is *additive* (new files alongside existing ones, selected by build config) rather than a rewrite.

## Architecture

### Target layout

```
src/
  main.cpp                    ← shrinks to ~300-400 LoC; lifecycle + state machine only
  hal/                        ← hardware concerns; StickC Plus impl
    display.h / .cpp          ← LCD ref, dims, brightness, sprite, orientation
    buttons.h / .cpp          ← A, B, power-button polling + hold helper
    imu.h / .cpp              ← accel read
    power.h / .cpp            ← USB/bat voltage + current, screen-breath, poweroff, LDO2
    beep.h / .cpp             ← tone + update
    rtc.h / .cpp              ← get/set time + date, weekday
    hal.h / .cpp              ← begin() + tick()
  screens/                    ← each file owns one screen's draw + local state
    clock.cpp
    stats.cpp                 ← drawPet + drawPetStats + drawPetHowTo + tinyHeart
    passkey.cpp
    approval.cpp
    menu.cpp
    settings.cpp
    reset.cpp
    hud.cpp
    info.cpp
  ble_bridge.h / .cpp         ← unchanged
  character.h / .cpp          ← unchanged (already takes TFT_eSPI*)
  buddy.h / .cpp              ← unchanged
  buddy_common.h              ← unchanged
  buddies/                    ← unchanged
  data.h                      ← one M5.Rtc call → hal::rtc::set(...)
  stats.h                     ← unchanged
  xfer.h                      ← three M5.Axp telemetry calls → hal::power::...
```

### HAL surface

Pure hardware. No settings gates, no UI state. Free functions in namespaces, implemented in matching `.cpp` files.

```cpp
namespace hal::display {
  void begin();                          // creates sprite, sets initial rotation
  TFT_eSPI&    lcd();                    // direct LCD (clock landscape, passkey)
  TFT_eSprite& sprite();                 // shared drawing surface
  int  width();                          // 135 on StickC Plus
  int  height();                         // 240
  void setRotation(uint8_t r);           // 0..3
  void push();                           // sprite → LCD
}

namespace hal::buttons {
  bool pressedA();
  bool pressedB();
  bool heldA(uint16_t ms);               // wraps M5.BtnA.pressedFor
  bool powerButtonPressed();             // AXP side button
}

namespace hal::imu {
  void readAccel(float& ax, float& ay, float& az);
}

namespace hal::power {
  float busVoltage();
  float batVoltage();
  float batCurrent();
  float axpTemp();
  void  setBrightness(uint8_t level);    // 0..5 → ScreenBreath(20 + lvl*20)
  void  setLcdPower(bool on);            // SetLDO2
  void  powerOff();
}

namespace hal::beep {
  void begin();
  void tick();
  void tone(uint16_t freq, uint16_t ms); // raw — caller gates on settings
}

namespace hal::rtc {
  struct Time { uint8_t h, m, s; };
  struct Date { uint8_t weekday, month, day; uint16_t year; };
  void getTime(Time&);
  void getDate(Date&);
  void setTime(const Time&);
  void setDate(const Date&);
}

namespace hal {
  void begin();                          // M5.begin(), then display/beep/imu init
  void tick();                           // M5.update() + beep::tick() per frame
}
```

Two boundary decisions:

- `hal::rtc` uses plain structs, not `RTC_TimeTypeDef` — translation happens inside the HAL. Keeps screens and `data.h` decoupled from the M5 library's type names.
- `hal::display::sprite()` returns the canonical sprite by reference — the `TFT_eSprite spr` global that lives in `main.cpp` today moves into `hal/display.cpp`. No compatibility `extern` shim; callers get the reference via the HAL.

### Screen modules

Each screen is a small self-contained file exposing a minimal API:

```cpp
// screens/<name>.h
namespace screen::<name> {
  void draw();                                   // renders into hal::display::sprite()
  bool handleButton(Button b, ButtonEvent e);    // interactive screens only; true if consumed
}
```

`Button` / `ButtonEvent` are defined in a small shared header `src/input.h` — included by both `main.cpp` and any interactive screen. They live outside the HAL because they're higher-level than raw button polls; `main.cpp` synthesizes them from `hal::buttons::*` state.

```cpp
// src/input.h
enum class Button       { A, B, Power };
enum class ButtonEvent  { Tap, LongPress, Release };
```

Per-screen responsibilities:

| Screen | Draw | Input | Local state |
|---|---|---|---|
| `clock` | ✓ | — | paintedOrient, lastSec |
| `info` | ✓ | — | — |
| `stats` | ✓ | ✓ | petPage (B cycles) |
| `passkey` | ✓ | — | — |
| `approval` | ✓ | ✓ | — |
| `hud` | ✓ | — | msgScroll, lastLineGen |
| `menu` | ✓ | ✓ | selected index |
| `settings` | ✓ | ✓ | selected index |
| `reset` | ✓ | ✓ | confirm state |

**Shared access**: screens read palette via `characterPalette()`, persistent data via `stats()` / `settings()` / `tama`. All device-neutral; none of these move.

**Screens deliberately do NOT**:
- Beep — state transitions beep at the caller (main) so screens stay pure render functions.
- Own the frame loop — each `draw()` is idempotent; main calls it once per frame.
- Know about other screens — no cross-screen references; transitions live in main's state machine.

### main.cpp after the refactor

```
main.cpp  (~300-400 LoC)
├─ globals        — displayMode, menu flags, nap/screenOff timers, USB-edge tracker
├─ helpers        — beep() [sound-gated], applyBrightness() [reads settings]
├─ input          — translates hal::buttons polls → Button/ButtonEvent events,
│                    handles tap-vs-long-press timing, swallow-first-press-on-wake
├─ state machine  — owns displayMode transitions, menu/settings/reset overlays,
│                    nap/screen-off timer, USB edge, prompt arrival, BLE passkey,
│                    xfer polling
├─ dispatch       — each frame: read events, route to active screen's
│                    handleButton() first; if unconsumed, run global actions
│                    (A-tap cycles displayMode, hold-A opens menu, etc.)
├─ frame render   — characterTick()/buddyTick(), active screen's draw(),
│                    any overlays, hal::display::push()
└─ setup()/loop() — hal::begin(), characterInit, bleInit, stats/settings load;
                    loop = hal::tick() + input + dispatch + render
```

**What leaves main.cpp entirely:**
- All ~15 `draw*()` functions → `screens/*.cpp`
- All direct `M5.*` calls → `hal/*`
- The `TFT_eSprite spr` global → `hal::display::sprite()`
- `tinyHeart()` → `screens/stats.cpp`

**What stays, by design:**
- Cross-screen coordination (state transitions, overlay ordering)
- Hardware + app-logic mixes (sound-gated `beep()`, settings-driven `applyBrightness()`)
- Orientation/clock-detection code (touches IMU + RTC + display; inherently cross-cutting)
- Edge-detection for BLE passkey, prompt arrival, USB change (drives transitions, not screens)

## Build configuration

**Phase A**: no `platformio.ini` changes. The existing `build_src_filter = +<*> +<buddies/>` already picks up `src/hal/` and `src/screens/` automatically. Same env, same lib_deps, same binary layout. NVS untouched across flashes.

**Phase B plug-in shape** (for reassurance only — not built in Phase A):

```ini
[env:m5stack-core2]
platform = espressif32
board = m5stack-core2
framework = arduino
...
build_src_filter =
    +<*> +<buddies/>
    -<hal/*>        -<screens/*>
    +<hal_core2/*>  +<screens_core2/*>
lib_deps =
    m5stack/M5Core2
    bitbank2/AnimatedGIF @ ^2.1.1
    bblanchon/ArduinoJson @ ^7.0.0
```

Phase B adds new source directories that implement the same `hal::*` namespaces and the same `screen::<name>` entry points, selected by the build filter. No shared source is touched. No `#ifdef DEVICE_…` pattern in application code: all device branching happens at the build-filter layer.

The Phase A design does NOT commit to `screens_core2/clock.cpp` (parallel dirs) vs `screens/clock_core2.cpp` (file-suffix). Either shape works; Phase B picks when it can see how much per-screen code actually diverges.

## Migration sequence

Ordered so that each step compiles, flashes, and behaves identically on-device. Each step is one commit.

### A.1 — HAL scaffolding (1 commit, no behavior change)

Create `src/hal/` with empty namespace headers and `.cpp` stubs that delegate directly to `M5.*`. No callers yet. Build passes; flash not required.

### A.2 — Migrate HAL concerns (6 commits, flash + smoke-test after each)

Ordered easiest → touchiest:

1. **beep** — 7 call sites, trivial wrap.
2. **rtc** — `data.h` setter + `clockRefreshRtc`; introduces plain-struct translation.
3. **power** — brightness (`applyBrightness`), USB detection, `SetLDO2`, `PowerOff`, `xfer.h` telemetry.
4. **imu** — 2 call sites (pose detection + clock orient).
5. **buttons** — `BtnA`/`BtnB` polling + `pressedFor` + AXP side button.
6. **display** — touchy:
   - Move `TFT_eSprite spr` ownership into `hal/display.cpp`; expose via `hal::display::sprite()`.
   - Replace every `spr.xxx()` and `M5.Lcd.xxx()` in main.cpp. Use `auto& spr = hal::display::sprite();` at the top of functions that draw heavily to minimize churn.
   - Replace `M5.Lcd.setRotation`, `M5.Lcd.fillScreen`, `pushSprite(0,0)` with HAL equivalents.

After A.2: no `M5.*` references remain in `main.cpp`, `data.h`, or `xfer.h`.

### A.3 — Migrate screens (9 commits, flash + test after each)

Create `src/screens/`, then move one screen at a time. Order (least state → most):

1. `passkey` — pure function, no state.
2. `info` — pure function, no state.
3. `hud` — `msgScroll`/`lastLineGen` statics move in.
4. `approval` — reads `tama.promptId`, no local state.
5. `clock` — `paintedOrient`, `lastSec` statics move in. Orientation *detection* stays in main (cross-cutting); only *drawing* moves.
6. `stats` — `drawPet` + `drawPetStats` + `drawPetHowTo` + `tinyHeart` + `petPage`.
7. `menu`, `settings`, `reset` — each owns selected index / confirm state.

After each move: main.cpp's call site becomes `screen::<name>::draw()`. Input handling still in main.cpp through this phase.

### A.4 — Input events + screen input handlers (1 commit)

- Add `Button` / `ButtonEvent` enums next to main's state machine.
- Replace inline tap/hold detection with a function that emits events.
- Add `screen::<name>::handleButton(...)` to `stats`, `approval`, `menu`, `settings`, `reset`; move their input handling out of main.cpp.
- main.cpp routes events to active screen first; falls back to global actions only if unconsumed.

### A.5 — Cleanup (1 commit)

- Remove unused includes (notably `#include <M5StickCPlus.h>` from main.cpp — it's only indirectly pulled through `hal/`).
- Delete stale comments pointing to moved code.
- Grep for any lingering `extern TFT_eSprite spr;` / `extern TFT_eSPI*` in non-HAL files.

**Total: ~17 commits.** Every commit flashes and behaves identically. A regression localizes to the last commit.

## Validation

### Code-level checks (automated, mechanical)

- `grep -r "M5\." src/ --exclude-dir=hal` → zero matches.
- `grep -r "TFT_eSprite spr" src/` → matches only `hal/display.cpp`.
- `grep -r "TFT_eSPI" src/` → matches only HAL + character + buddy (the three that legitimately accept a TFT reference as a parameter).
- `main.cpp` line count under 500 (from 1265).

### On-device walkthrough (manual; full after A.5, spot-check after each A.3 screen)

Flows to exercise:

1. **Boot** — device comes up, character loads, animates idly.
2. **Display modes** — A-tap walks NORMAL → INFO → PET → NORMAL.
3. **Pet screen** — mood/fed/energy render (evenly spaced, size-2 grid values, no overlap), B cycles page.
4. **Menu** — long-hold A opens, A/B navigate, selection works, back returns.
5. **Settings** — each item toggles/changes; values persist across reboot (NVS intact).
6. **Reset** — confirm/cancel flow; confirming clears NVS.
7. **Feedback** — beeps fire on prompt arrival, approval, wake, menu nav; brightness setting visibly applies.
8. **BLE pairing** — fresh pair shows 6-digit passkey; bonded reconnect silent.
9. **Approval prompt** — A approves, B denies; APR/DNY stats increment; beeps fire.
10. **Power/nap** — face-down naps, any button wakes (first press swallowed), idle → screen off, any button → on.
11. **HUD** — during a Claude session, transcript lines scroll in the HUD area.
12. **XFer** — drag a character folder from Claude Desktop; progress bar shows; new character loads.

### Regression risk

The recently-tuned stats format rules (`800` / `1.6K` / `400K` / `1.5M` ladder) and the stats grid layout (full-width TOK row, even sprite spacing) are the latest code to change. They land in `screens/stats.cpp`. Verify that screen closely for pixel drift even though the acceptance criterion permits minor shifts.

### Acceptance

All code checks green; all feature flows pass a manual walk-through; no user-visible regression.
