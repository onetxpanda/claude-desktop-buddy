# Phase B.1 — M5Unified Library Migration (design)

- **Date**: 2026-04-24
- **Phase**: B.1 of B (B.2 adds Core2 HAL; B.3 adds Core2 layouts).
- **Prerequisite**: Phase A (HAL refactor) complete on `hal-refactor` branch.
- **Scope**: Replace `m5stack/M5StickCPlus` with `m5stack/M5Unified` as the sole M5 library. Swap display types (`TFT_eSprite` → `M5Canvas`, `TFT_eSPI` → `M5GFX`). Rename the shared sprite variable `spr` → `canvas`. Single build target: `m5stickc-plus`.
- **Acceptance criterion**: code-level only. Build succeeds, grep-based invariants pass. No device-level testing required.
- **Out of scope**: Core2 support (B.2), Core2 layout variants (B.3), any feature changes.

## Why

Adding Core2 support (Phase B.2) cleanly requires a single M5 library that covers both devices. `M5Unified` is that library — it unifies Core / Core2 / CoreS3 / StickC / StickCPlus / StickCPlus2 / Atom family under one API. Migrating the StickC HAL to M5Unified *before* adding Core2 means:

- The migration is validated against a single known-good device.
- Rollback is a single-commit revert if anything regresses.
- Core2 (B.2) becomes purely additive — a new HAL implementation in a sibling directory, selected via `build_src_filter`.

## Architecture

### Library swap

`platformio.ini`:

- `lib_deps`: `m5stack/M5StickCPlus` → `m5stack/M5Unified`.
- `board` stays `m5stick-c`. All other config unchanged.

### Display-type swap

M5Unified's display backend is M5GFX (a LovyanGFX derivative), not TFT_eSPI. The LovyanGFX API is deliberately TFT_eSPI-compatible at the method level (same `fillRect`, `drawString`, `setTextColor`, `pushSprite`, `createSprite`, etc.), so method call sites don't change — only the type names:

| Before | After |
|---|---|
| `TFT_eSPI` | `M5GFX` |
| `TFT_eSprite` | `M5Canvas` |
| `TFT_eSprite(&M5.Lcd)` | `M5Canvas(&M5.Display)` |

Consumer method calls (`fillSprite`, `fillRect`, `drawString`, etc.) are unchanged.

### Global identifier rename

Phase A introduced a global `TFT_eSprite& spr = hal::display::sprite();` in `main.cpp`, with `extern TFT_eSprite& spr;` declarations in 22 consumer files. This phase renames:

- `spr` → `canvas` (the variable)
- `TFT_eSprite&` → `M5Canvas&` (the type)

Every consumer file updates both. No shim or typedef is used — the old names disappear in the same commit the new ones appear.

### API migration table (M5StickCPlus → M5Unified)

Drives the HAL `.cpp` rewrites. Public HAL signatures (`hal::display::*`, `hal::power::*`, etc.) stay stable except for display return types; HAL internals shift to M5Unified's APIs.

**Display:**

| Old | New |
|---|---|
| `M5.Lcd` | `M5.Display` |
| `M5.Lcd.setRotation(r)` | `M5.Display.setRotation(r)` |
| `M5.Lcd.fillScreen(c)` | `M5.Display.fillScreen(c)` |

**Power (formerly AXP):**

| Old | New |
|---|---|
| `M5.Axp.ScreenBreath(n)` | `M5.Display.setBrightness(n)` — brightness moves to Display class |
| `M5.Axp.SetLDO2(true)` / `(false)` | `M5.Display.wakeup()` / `M5.Display.sleep()` |
| `M5.Axp.PowerOff()` | `M5.Power.powerOff()` |
| `M5.Axp.GetVBusVoltage()` (volts) | `M5.Power.getVBUSVoltage()` (millivolts — HAL normalizes to volts) |
| `M5.Axp.GetBatVoltage()` (volts) | `M5.Power.getBatteryVoltage()` (millivolts — HAL normalizes) |
| `M5.Axp.GetBatCurrent()` (mA) | `M5.Power.getBatteryCurrent()` (mA) |
| `M5.Axp.GetTempInAXP192()` (°C) | **Dropped.** Not exposed in M5Unified's Power API. The `hal::power::axpTemp()` declaration is removed from `hal/power.h`; the INFO screen's temperature line is dropped. |

**Buttons:**

| Old | New |
|---|---|
| `M5.BtnA.isPressed()` / `pressedFor(ms)` / `wasReleased()` | Same method names on M5Unified |
| `M5.BtnB.isPressed()` / `wasPressed()` | Same |
| `M5.Axp.GetBtnPress() == 0x02` | `M5.BtnPWR.wasClicked()` — M5Unified has a dedicated power-button class |

**IMU:**

| Old | New |
|---|---|
| `M5.Imu.Init()` | `M5.Imu.begin()` — name differs |
| `M5.Imu.getAccelData(&x, &y, &z)` | `auto d = M5.Imu.getImuData(); ax = d.accel.x; ay = d.accel.y; az = d.accel.z;` — struct-returning API |

M5Unified does **not** define `#define imu Imu`, so the three `#undef imu` workarounds introduced in Phase A (`src/hal/hal.cpp`, `src/hal/imu.cpp`, `src/main.cpp`) are removed.

**Speaker (formerly Beep):**

| Old | New |
|---|---|
| `M5.Beep.begin()` | `M5.Speaker.begin()` — invoked by `M5.begin()` automatically |
| `M5.Beep.update()` | No-op / removed — M5Unified's Speaker manages timing internally |
| `M5.Beep.tone(freq, ms)` | `M5.Speaker.tone(freq, ms)` — identical signature |

**RTC:**

| Old | New |
|---|---|
| `RTC_TimeTypeDef t; M5.Rtc.GetTime(&t);` | `auto dt = M5.Rtc.getDateTime(); out.h = dt.time.hours; ...` |
| `RTC_DateTypeDef d; M5.Rtc.GetDate(&d);` | Same combined `dt` — `dt.date.year / month / date / weekDay` |
| `M5.Rtc.SetTime(&t); M5.Rtc.SetDate(&d);` | `m5::rtc_datetime_t dt{}; dt.time.hours = ...; ... M5.Rtc.setDateTime(dt);` |

The HAL's plain `hal::rtc::Time` / `hal::rtc::Date` structs stay unchanged — the translation lives entirely inside `src/hal/rtc.cpp`.

**Lifecycle:**

| Old | New |
|---|---|
| `M5.begin()` | `M5.begin()` — optional config struct available but not required |
| `M5.update()` | `M5.update()` |

### Brightness preservation

StickC Plus's `M5.Axp.ScreenBreath(n)` accepted `n ∈ [0, 100]` (roughly). M5Unified's `M5.Display.setBrightness(n)` takes `n ∈ [0, 255]`. The HAL exposes `hal::power::setBrightness(uint8_t level)` with `level ∈ [0, 4]` (Phase A's `brightLevel = (brightLevel + 1) % 5` cycling).

The HAL keeps the exact same internal mapping as Phase A: `20 + level * 20` (i.e., 20 / 40 / 60 / 80 / 100) and passes that to `M5.Display.setBrightness(...)`. Since `M5.Display.setBrightness` accepts the full 0-255 range, the old values remain valid and produce visually-equivalent backlight levels. No tuning — any brightness rebalance is a separate future task.

## Files touched

~32 files. Every change is mechanical type/name substitution; no logic changes.

**Modified:**

- `platformio.ini` — `lib_deps` swap
- `src/hal/display.h` — types, include header swap
- `src/hal/display.cpp` — sprite type, init call
- `src/hal/power.cpp` — Axp → Power/Display API; drop `axpTemp()`
- `src/hal/power.h` — drop `axpTemp()` declaration
- `src/hal/beep.cpp` — Beep → Speaker
- `src/hal/imu.cpp` — `begin()` rename, struct-returning API
- `src/hal/rtc.cpp` — combined `getDateTime()` / `setDateTime()` API
- `src/hal/buttons.cpp` — power-button API change
- `src/hal/hal.cpp` — remove `#undef imu`
- `src/hal/imu.h` — already has `begin()`; no change
- `src/main.cpp` — `spr` → `canvas` throughout; type rename; remove `#undef imu`; drop INFO-screen temp line reference if inlined (likely already in `src/screens/info.cpp`)
- `src/screens/info.cpp` — drop the AXP-temperature line
- `src/character.h` / `src/buddy.h` — `TFT_eSPI*` → `M5GFX*` in function signatures (`characterRenderTo`, `buddyRenderTo`)
- `src/character.cpp` — extern + body renames
- `src/buddy.cpp` — extern + body renames
- `src/buddies/*.cpp` — 18 files; extern + body renames
- `src/screens/*.cpp` — 9 files; extern + body renames

**Unchanged:** `src/ble_bridge.*`, `src/stats.h`, `src/data.h`, `src/xfer.h`, `src/input.h`, `src/buddy_common.h`, `no_ota.csv`.

## Migration sequence

Because the library swap invalidates every `TFT_eSprite` / `TFT_eSPI` / `M5.Axp` / `M5.Beep` / `M5.Rtc` reference simultaneously, the migration lands as **one atomic commit**. Intermediate splits would require a shim or a non-building intermediate commit, both of which are rejected.

### Task 1 — Single-commit migration

Apply every mapping from the API table above. Rename every identifier per Section "Global identifier rename." Touch every file listed in "Files touched." Drop the AXP temperature line.

Verify:

- `pio run` exits 0.
- Grep invariants (listed below) all pass.

Commit message: `Migrate M5StickCPlus → M5Unified; rename spr → canvas`.

**Total: 1 commit.**

## Validation / acceptance

### Code-level invariants (sole acceptance gate)

```bash
# Build cleanly
/Users/stephenoliver/.platformio/penv/bin/pio run

# No TFT_eSPI types remain
grep -rn "TFT_eSprite\|TFT_eSPI" src/    # zero non-comment matches

# No M5.Axp / M5.Beep / M5.Lcd calls remain
grep -rn "M5\.Axp\|M5\.Beep\|M5\.Lcd" src/   # zero non-comment matches

# Old library string gone from config and code
grep -rn "M5StickCPlus" src/ platformio.ini  # zero

# spr renamed to canvas
grep -rn "\bspr\b" src/                      # zero

# imu macro workaround removed
grep -rn "#undef imu" src/                   # zero
```

All greps must return zero. Build must be SUCCESS.

### Acknowledged behavior deltas (not regressions)

- INFO screen no longer shows AXP192 die temperature. Line dropped.
- Font glyph rendering may have 1-2 pixel sub-pixel differences due to LovyanGFX vs TFT_eSPI rendering. Glyph shapes otherwise identical.
- Brightness levels 0-4 still map to raw values 20/40/60/80/100 — identical to Phase A. No change.

### NVS preservation

Flash range is app/bootloader/partition/otadata only. NVS at `0x9000–0xdfff` untouched across flash. Settings, stats, and BLE bonds persist. Structural — not a test case.

### Acceptance

Greps green + build green = done. No on-device walkthrough required.
