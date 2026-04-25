# Phase B.2 — Core2 Build Target (design)

- **Date**: 2026-04-24
- **Phase**: B.2 of B (prerequisites: A and B.1; successor: B.3 Core2 landscape layouts).
- **Prerequisite**: Phase B.1 (M5Unified migration) complete.
- **Scope**: Add `m5stack-core2` as a second PlatformIO env using the existing source tree. Make `hal::display` dimensions parametric from M5Unified's runtime display info. Remove the hardcoded rotation call so M5Unified's per-board defaults take effect.
- **Acceptance**: code-level only. Both `pio run` environments exit 0; HAL carries no hardcoded dimension literals. No device-level testing required.
- **Out of scope**: Core2 screen layout redesign (B.3), vibration motor, speaker volume, touch input, SD card, 3rd virtual button, StickC behavior changes.

## Why

Phase A's spec anticipated a separate `src/hal_core2/` directory selected via `build_src_filter`, because it was written before M5Unified became the HAL backend. With M5Unified (landed in B.1) now handling board-level differences internally, ~95% of the HAL code is genuinely device-neutral — only display dimensions and initial rotation remain board-specific. A single shared HAL directory with parametric dimensions is simpler, smaller, and better matches the library's abstraction boundaries. No second HAL directory, no `#ifdef` in application code, no duplicated logic.

## Architecture

### Build configuration

`platformio.ini` gains a second env block. Both envs share source tree (`build_src_filter = +<*> +<buddies/>`) and lib_deps (`m5stack/M5Unified` + AnimatedGIF + ArduinoJson). The only env-level difference is the board:

- `[env:m5stickc-plus]` — `board = m5stick-c`, `board_build.f_cpu = 160000000L` (existing).
- `[env:m5stack-core2]` — `board = m5stack-core2`, default CPU clock (240 MHz — Core2's stock speed). No explicit f_cpu override.

Both envs keep `board_build.filesystem = littlefs` and `board_build.partitions = no_ota.csv`.

### HAL adjustments (only `src/hal/display.cpp` touched)

Four changes; the surrounding code stays identical:

1. `M5.Display.setRotation(0);` in `begin()` — **deleted**. M5Unified applies each board's sensible default (StickC: 0 / portrait 135×240; Core2: 1 / landscape 320×240).
2. `_spr.createSprite(135, 240);` in `begin()` — **becomes** `_spr.createSprite(M5.Display.width(), M5.Display.height());` (sized to whatever the detected display reports).
3. `int width() { return 135; }` — **becomes** `int width() { return M5.Display.width(); }`.
4. `int height() { return 240; }` — **becomes** `int height() { return M5.Display.height(); }`.

Every other HAL file is unchanged. M5Unified's implementation auto-adapts to the board (MPU6886, AXP192, BM8563 RTC all present on both devices; speaker routes to piezo on StickC, NS4168+speaker on Core2; buttons are virtual touch zones on Core2, physical on StickC — the M5Unified API is identical either way).

### Screen/layout behavior after this change

Screens continue to draw with their Phase A layouts (portrait 135×240-oriented). On StickC this is unchanged — `hal::display::width()` still returns 135, `height()` returns 240. On Core2 (default landscape rotation, 320×240):

- Indicator rows using `(W * (2*i + 1)) / N` patterns (hearts, dots, bars) auto-space across the wider canvas. Hearts spread 4× further apart horizontally. Looks odd but functional.
- Stats grid elements using `W / 4` / `3W / 4` centers land at x=80 and 240. Content fits on screen.
- Vertical layouts (y positions 82 through 238) fit unchanged — Core2 has the same 240 height when in landscape orientation.
- Character sprite renders in its 70-pixel top strip starting at x=0 — appears in the left portion of Core2's 320-wide top band with empty space to the right.

This produces the intended "functional but visually suboptimal on Core2" state for B.2. Phase B.3 adds per-screen landscape layouts.

### Sprite memory

StickC: 135 × 240 × 2 bytes = ~65 KB. Existing StickC firmware uses ~76 KB total RAM (per B.1 build output), leaving plenty of heap room.

Core2: 320 × 240 × 2 bytes = ~150 KB. ESP32-PICO-D4 has ~290 KB free heap on Arduino. Total projected Core2 RAM: ~76 + (150 − 65) ≈ 160 KB. Fits, with ~130 KB headroom. If Core2 `createSprite` fails at runtime (detected as an empty-pixel canvas), the fallback is to use 8 bpp (halve memory) — not implemented in this spec but noted for future reference.

## Files touched

**Modified:**
- `platformio.ini` — add `[env:m5stack-core2]` block
- `src/hal/display.cpp` — four line changes per "HAL adjustments" above

**Unchanged:** everything else.

## Migration sequence

Single commit. Two file edits. No intermediate state.

### Task 1 — Add Core2 build target

1. Edit `platformio.ini` to append `[env:m5stack-core2]`.
2. Edit `src/hal/display.cpp` to make dimensions parametric and remove the `setRotation(0)` call.
3. Build both envs: `pio run -e m5stickc-plus` and `pio run -e m5stack-core2`. Both must succeed.
4. Verify the HAL-dimension invariant: `grep -rn "\b135\b\|\b240\b" src/hal/` returns zero non-comment matches.
5. Commit with message `Add m5stack-core2 env; parametric display dims`.

**Total: 1 commit, 2 files modified.**

## Validation / acceptance

### Code-level invariants (sole acceptance gate)

```bash
# Both envs build clean
/Users/stephenoliver/.platformio/penv/bin/pio run -e m5stickc-plus
/Users/stephenoliver/.platformio/penv/bin/pio run -e m5stack-core2

# No hardcoded dims leaked in HAL
grep -rn "\b135\b\|\b240\b" src/hal/   # zero non-comment matches
```

Both builds must succeed. Grep must return zero.

### Acknowledged deltas (not regressions)

- `hal::display::width()` / `height()` now compute their return value at each call via `M5.Display.width()` / `height()`. On StickC this returns 135 / 240 as before. On Core2, 320 / 240 (default landscape orientation).
- `M5.Display.setRotation(0)` is no longer called explicitly in `hal::display::begin()`. StickC net orientation unchanged (M5Unified applies rotation 0 by default). Core2 gets rotation 1 (landscape) by default.
- Core2 firmware displays portrait-sized layouts on a landscape canvas — visually suboptimal by design. B.3 fixes layouts.

### NVS preservation

Flash partition layout unchanged (still `no_ota.csv`). NVS at `0x9000–0xdfff` untouched on flash. Settings, stats, BLE bonds persist on both devices.

### Acceptance

Both builds green + grep clean = done.
