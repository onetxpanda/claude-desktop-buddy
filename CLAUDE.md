# CLAUDE.md

Context for future Claude sessions working on this firmware. Reflects the state of the `hal-refactor` branch (B.3 layouts in flight), not yet merged to `main`.

## What this is

Tamagotchi-style buddy firmware for M5 hardware that bridges to Claude Desktop over BLE. The desktop sends transcript snapshots, prompts, and approval requests; the device displays a character, tracks stats (approvals/denials/tokens), and lets the user approve/deny prompts via physical buttons.

This started as a single-board firmware for **M5StickC Plus** (135×240 portrait). The work on `hal-refactor` is generalizing it to also run on **M5Stack Core2** (320×240 landscape) without forking the codebase.

## Build / flash

PlatformIO, two envs sharing the same `src/` tree:

```bash
# StickC Plus
/Users/stephenoliver/.platformio/penv/bin/pio run -e m5stickc-plus
/Users/stephenoliver/.platformio/penv/bin/pio run -e m5stickc-plus -t upload

# Core2
/Users/stephenoliver/.platformio/penv/bin/pio run -e m5stack-core2
/Users/stephenoliver/.platformio/penv/bin/pio run -e m5stack-core2 -t upload
```

Uploads write only bootloader/partition/otadata/app — **NVS at `0x9000–0xdfff` is preserved** across flashes. Settings, stats, BLE bonds survive.

Toolchain note: clang's lint diagnostics get the ESP toolchain flags wrong and constantly report false-positive errors (`'M5Unified.h' file not found`, `Unknown argument '-mlongcalls'`). PlatformIO builds correctly. **Trust the build, ignore clang diagnostics.**

## Architecture (post Phase A + B)

```
src/
  main.cpp                ← lifecycle, state machine, input event synthesis (~700 LoC)
  input.h                 ← Btn / BtnEvent enums (renamed from Button to dodge M5 collision)
  hal/                    ← single shared HAL across both boards via M5Unified
    display.h, display.cpp
    buttons.h, buttons.cpp
    imu.h, imu.cpp
    power.h, power.cpp
    beep.h, beep.cpp
    rtc.h, rtc.cpp
    hal.h, hal.cpp        ← begin() / tick()
  screens/                ← one file per screen, all device-neutral
    clock.cpp             ← currently disabled (`bool clocking = false`)
    stats.cpp             ← namespace screen::petstats; recently-tuned grid layout
    passkey.cpp, info.cpp, hud.cpp, approval.cpp
    menu.cpp, settings.cpp, reset.cpp
    menu_hints.h          ← shared header for footer-hint helper
  character.cpp           ← GIF + text-mode character renderer; uses `peekTop()` runtime
  buddy.cpp               ← ASCII-art species renderer; uses `buddyCanvasW()` runtime
  buddies/<species>.cpp   ← 18 ASCII species (cat, dragon, octopus, etc.)
  ble_bridge.cpp          ← NimBLE-Arduino implementation of Nordic UART Service
  data.h, stats.h, xfer.h ← persistent state, Claude bridge protocol, file-xfer protocol
```

Key abstractions:

- **`canvas`** is the global `M5Canvas&` reference (renamed from `spr` in B.1). It points to a sprite owned by `hal/display.cpp`. Every screen draws into it; `hal::display::push()` blits it to the LCD.
- **`hal::display::width()` / `height()`** return runtime values from `M5.Display`, so layout math adapts per board.
- **`hal::display::isLarge()`** returns `true` when width ≥ 320 (Core2-class). Per-screen and per-renderer code branches on this for size-2 → size-3 text bumps, larger sprite radii, taller character region (`peekTop()`), wider buddy canvas (`buddyCanvasW()`).

## Hardware quirks (the hard-earned knowledge)

These all came out of B.2/B.3 debugging. Document them so future you doesn't re-derive them.

### 1. Core2 PSRAM + DMA cache coherency

PSRAM-backed sprites on Core2 produce visual garbage (the famous "white and green lines") when pushed via `M5GFX::pushSprite`. The CPU writes to the sprite via cache; DMA reads from PSRAM directly and sees stale data.

**Fix in `hal/display.cpp`**: on PSRAM-equipped boards (`psramFound()`), force `_spr.setPsram(false)`. Internal RAM is DMA-coherent.

But: at 16bpp, a 320×240 sprite is 150 KB which doesn't fit in internal RAM alongside the BLE stack. So Core2 uses **8bpp RGB332** mode (76 KB). StickC stays at 16bpp (no PSRAM, sprite is 65 KB, fits trivially).

`createPalette()` is **deliberately not called** on Core2 — paletted 8bpp would require all drawing to use palette indices, which would require rewriting every screen's color usage. Without `createPalette()`, the canvas is in RGB332 mode (R3-G3-B2 packed in 1 byte): drawing with raw 16bpp colors auto-quantizes to RGB332 directly, and pushing to the 16bpp display expands RGB332 → RGB565 via formula. Coarser color than full 16bpp but actually colorful.

### 2. M5StickCPlus library macro pollution (avoided now)

The old M5StickCPlus library defined `#define imu Imu` for backward compat, which collided with our `hal::imu` namespace. We worked around it with `#undef imu` in three files. **B.1 migrated to M5Unified, which does not define this macro** — workarounds removed.

### 3. Bluedroid BLE spinlock crash on Core2

The default arduino-esp32 v2.x Bluedroid stack hits a spinlock assertion (`spinlock.h:122`) inside `attp_build_sr_msg` / `GATTS_SendRsp` when a paired peer subscribes to a TX characteristic. This is a known Core2-specific instability — works fine on StickC.

**Fix**: B.2 swapped to **NimBLE-Arduino** (`h2zero/NimBLE-Arduino @ ^2.0.0`). Different stack entirely, dodges the bug. Bonus: ~520 KB smaller flash footprint.

We also tried bumping the platform to **pioarduino** (arduino-esp32 v3.x), which fixes the Bluedroid bug but introduces an IRAM overflow we couldn't work around at compile time. The v2 → v3 BLE API compat fixes (`auto v = c->getValue()`, `#if ESP_ARDUINO_VERSION` for `setEncryptionLevel`, `esp_mac.h` includes) were reverted with the platform.

### 4. LittleFS auto-format on fresh devices

A fresh Core2 has an uninitialized LittleFS partition. `LittleFS.begin(false)` returns false, then downstream code calls a LittleFS function on the unmounted FS and triggers a spinlock assertion crash (boot loop).

**Fix in `character.cpp`**: `LittleFS.begin(true)` formats on first failure. Existing devices unaffected.

### 5. Static initialization order (sprite reference)

`M5Canvas _spr` is a file-scope static in `hal/display.cpp`; `M5Canvas& canvas` is a global reference in `main.cpp` (defined as `M5Canvas& canvas = hal::display::sprite()`). Cross-TU static init order is undefined in standard C++, but PlatformIO's link order happens to put `hal/display.cpp` before `main.cpp`, and the existing M5Stack code already relied on similar init ordering (`M5.Lcd` member of the M5 global). Working in practice; no shim needed.

`character.cpp` and `buddy.cpp` use `extern M5Canvas& canvas;` to access it. Their `_tgt` pointer (used by `characterRenderTo` / `buddyRenderTo` for direct LCD drawing) is `lgfx::LGFXBase*` — the common base of `M5Canvas` and `M5GFX`, since `M5Canvas*` doesn't widen to `M5GFX*` cleanly.

### 6. M5StickC Plus rotation 0 = portrait; Core2 rotation 1 = landscape (default)

We deliberately removed the `M5.Display.setRotation(0)` from `hal::display::begin()` so each board gets M5Unified's per-board default rotation. StickC stays portrait, Core2 becomes landscape.

## Phases shipped (on `hal-refactor` branch)

- **A** (commits before `370b569`): refactored monolithic `main.cpp` (1265 LoC) into HAL + screens. ~17 commits. Spec/plan in `docs/superpowers/specs/2026-04-24-phase-a-device-hal-refactor-design.md` + corresponding plan file.
- **B.1**: migrated `M5StickCPlus` → `M5Unified`; renamed `spr` → `canvas`, `TFT_eSprite` → `M5Canvas`, `TFT_eSPI` → `M5GFX`. Single atomic commit `3b17907`. Spec: `2026-04-24-phase-b1-m5unified-migration-design.md`.
- **B.2**: added `m5stack-core2` PlatformIO env. Made display dims parametric. Plus 3 follow-up fixes: Core2 PSRAM workaround (8bpp/internal RAM), LittleFS auto-format, NimBLE migration. Spec: `2026-04-24-phase-b2-core2-build-target-design.md`.
- **B.3** (in progress): per-screen layout adaptations on Core2 via `hal::display::isLarge()`. Larger fonts/sprites/character region where space allows. Commit `0900e19` plus the RGB332-mode color fix (uncommitted/in flight). Spec: `2026-04-25-phase-b3-core2-layouts-design.md`.

Each phase has a matching design doc (`specs/`) and implementation plan (`plans/`). Use them as reference rather than re-deriving.

## Where things stand right now (2026-04-25)

- `hal-refactor` is ~28 commits ahead of `main`. Not yet merged.
- StickC Plus: works end-to-end. NimBLE pairs cleanly, all screens render at 16bpp.
- Core2: boots, displays UI, NimBLE pairs cleanly. **Color fidelity is the active issue** — at 8bpp RGB332 (current), greys looked okay but tinted text was washed out; iteration in progress to get colors looking right with the constrained palette.

## Likely future direction

In rough priority order:

1. **Finish B.3 color tuning**. Either get RGB332 looking acceptable or bite the bullet and find a way to do 16bpp with PSRAM cache flush. Possible path: explicit `Cache_WriteBack_Addr()` from `<rom/cache.h>` before each pushSprite. We didn't try this yet because the call may not be in arduino-esp32 v2's public API, but it's the canonical solution if available.

2. **Merge `hal-refactor` to `main`** once Core2 is visually solid. The branch is a substantial improvement either way; even without Core2, the HAL + screens split + M5Unified + NimBLE migration are net wins on StickC.

3. **Phase B.4 (deferred): touch gestures on Core2**. Swipe-left/right to change primary screens. M5Unified exposes touch via `M5.Touch.getDetail()`. Would slot into the existing `Btn` / `BtnEvent` event system as new event types.

4. **Phase A.6 / future: deep-sleep on nap**. Documented in the original Phase A spec under "Deferred". MPU6886's INT pin → GPIO 35 (RTC-capable) means motion-wake from deep sleep is achievable. Scope estimate: 150-300 LoC. Cleanest to do after the layout/color work settles.

5. **Possible: re-enable charging clock**. `bool clocking = false` in `main.cpp` was hard-disabled by the user mid-session ("Disable clock" commit `acd15e3`). The clock face code lives in `screens/clock.cpp` and works (last verified before B.3). Future could either delete the clock entirely or restore it as a settings-toggleable feature.

6. **CoreS3 and other M5 boards**. The architecture (M5Unified + parametric HAL + `isLarge()` predicate) generalizes naturally. Adding a CoreS3 env should be near-zero new code, just a third PlatformIO `[env:]` block. Same applies to AtomS3, StickCPlus2, etc.

## Working style / conventions

- **No tests.** Firmware has no unit-test harness; verification is build success + on-device smoke. Code-level invariants (greps for "no `M5.*` outside `src/hal/`", "no `TFT_eSprite` outside hal/display.cpp", etc.) substitute where they can.
- **`docs/superpowers/specs/` and `docs/superpowers/plans/`** hold the design rationale and step-by-step migration plans for each phase. New work should follow the same pattern: brainstorm → spec → plan → execute.
- **Every M5 hardware call goes through `hal::*`.** Adding new hardware features means extending the HAL, not reaching into `M5.*` from screens or app code.
- **No `#ifdef DEVICE_CORE2` in app code.** Per-board variation lives in `hal/` (auto-handled by M5Unified) or behind `hal::display::isLarge()`.
- **Plain identifiers, minimal comments.** The codebase has tight, idiomatic comments where the *why* is non-obvious; avoid commenting the *what*.
- **Sprite name is `canvas`**, not `spr`. The type is `M5Canvas` (not `TFT_eSprite`). LCD reference is `hal::display::lcd()` returning `M5GFX&`.

## Things that look like bugs but aren't

- The 18 buddy `.cpp` files all have the same `extern M5Canvas& canvas;` declaration. That's intentional — they share access to the sprite via the global reference.
- `screens/clock.cpp` exists but is unreachable in normal flow (clocking is disabled). Don't delete it; it's not dead code, just gated.
- `bool clocking = false;` in `main.cpp` is the disable. Comment out / set `true` to re-enable for testing.
- `_tgt` in `character.cpp` and `buddy.cpp` is `lgfx::LGFXBase*` rather than `M5GFX*` — required for assignment compatibility with `M5Canvas&`.

## Branch state quick check

```bash
git branch --show-current   # expect: hal-refactor (or main)
git log --oneline main..hal-refactor | head -30   # full B-branch commit list
```

If `hal-refactor` was already merged, this is post-history; check `git log` for context.
