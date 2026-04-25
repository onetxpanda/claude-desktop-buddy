# Phase B.3 — Core2 Landscape Layout Adaptations (design)

- **Date**: 2026-04-25
- **Phase**: B.3 of B (final). Prerequisites: A, B.1, B.2 complete.
- **Scope**: Adapt the existing screen layouts so they fit Core2's 320×240 landscape canvas without looking broken, and use the extra horizontal real estate for larger fonts / sprites where space allows. Single shared screen sources continue (no per-device variant directories) — adaptation happens via inline `hal::display::isLarge()` checks.
- **Out of scope**: Touch gestures, swipe-to-change-screen, side-by-side multi-panel layouts, Core2-only features (vibration motor, etc.). StickC behavior is preserved by construction (`isLarge()` returns false there).
- **Acceptance**: code-level only. Both envs build, the `isLarge()` helper is wired through the expected files. No on-device verification gate.

## Why

Phase B.2 made Core2 functional but visually suboptimal — the StickC portrait layouts (135-wide) render in a cramped top-left region of Core2's 320×240 landscape canvas, with text and indicators that are smaller than the screen comfortably affords. This phase fits the layouts to the new canvas: larger fonts, larger sprites, wider character region. StickC code paths remain unchanged.

Decided in B.2: a single shared `src/hal/` and `src/screens/` directory across both boards, with parametric width math via `hal::display::width()` rather than per-device variant files. This phase extends that pattern with a new `hal::display::isLarge()` predicate for branch points where parametric scaling isn't sufficient (e.g., font sizes, sprite radii, character region height).

## Architecture

### HAL helper

Single new function in `src/hal/display.{h,cpp}`:

```cpp
// src/hal/display.h — append within namespace hal::display
bool isLarge();   // true when display width ≥ 320 (Core2-class screens)

// src/hal/display.cpp
bool isLarge() { return M5.Display.width() >= 320; }
```

**Threshold rationale**: M5StickC and M5StickC Plus are <240 wide; Core, Core2, CoreS3 are 320 wide. The 320 threshold cleanly splits Stick-class small displays from Core-class large displays.

The function is one line, runtime-cheap, and matches the codebase's existing pattern of consulting `M5.Display.width()` directly. No build-time `#ifdef` is introduced.

### Per-screen adaptations

Pattern: where current code uses a hardcoded `setTextSize` or sprite radius, branch on `hal::display::isLarge()` to a larger value on Core2. Where horizontal positions already use `width()`-aware math (e.g., `(W * (2*i+1)) / N`), no change needed — they auto-distribute on the wider canvas.

| Screen | Adaptation when `isLarge()` |
|---|---|
| **stats.cpp** | Hearts r=4 → r=6. Fed dots r=4 → r=5. Energy bars 15×10 → 22×14. Lv badge 42×14 → 60×18 with size-2 inner text (was size-1). Grid values stay size-2 (recently tuned in this session); 3-letter labels stay size-2. Existing `(W * (2*i+1)) / N` math auto-distributes indicators across 320px width. Grid `colCenterX` auto-adapts. |
| **info.cpp** | All `setTextSize(1)` → `setTextSize(2)`. Vertical line height 9 → 16. Section header rows bump to size-3 where present. |
| **passkey.cpp** | 6-digit passkey font scales up ~1.5x. Centered on `width()/2` — already auto-adapts horizontally. |
| **approval.cpp** | "approve?" header → size-3. Button-hint text → size-2. Body text wraps as before. |
| **menu.cpp** | Item text size-2 → size-3. Row pitch grows accordingly. Menu has 6 items; fits at size-3 in 240 px height. |
| **settings.cpp** | Stays size-2 (10 items × size-3 row pitch wouldn't fit 240 px height). |
| **reset.cpp** | Item text size-2 → size-3. Three items, fits easily. |
| **hud.cpp** | Message scroll size-1 → size-2. Line height 8 → 16. Visible-line count stays 3. |
| **clock.cpp** | Skipped — currently disabled (`bool clocking = false`). Existing landscape-mode draw path handles Core2's default landscape rotation by accident. Future clock re-enable can tune. |
| **character.cpp / buddy.cpp / buddy_common.h** | `PEEK_TOP = 70` in character.cpp becomes a runtime function: `int peekTop()` returning 100 on large, 70 otherwise. `BUDDY_CANVAS_W = 100` similarly: a function returning 160 on large, 100 otherwise. Affected arithmetic expressions update mechanically — ~10 sites per file. |

### Implementation note on PEEK_TOP and BUDDY_CANVAS_W

`PEEK_TOP` and `BUDDY_CANVAS_W` are currently `static const int` at file scope, used in numerous arithmetic expressions inside `character.cpp` and `buddy.cpp` respectively. Converting them to runtime function calls means each use site changes from `PEEK_TOP` to `peekTop()`. The helper functions live as file-scope statics in the same `.cpp` files (no header surface change). The arithmetic compiles unchanged otherwise.

If a use site computes a value at static-init time (rare in this code), it stays a compile-time constant of the StickC value — only runtime call sites get the device-aware value. For B.3's purposes, all uses I can identify are runtime-evaluated.

## Files touched

- `src/hal/display.h` — add `isLarge()` declaration
- `src/hal/display.cpp` — add `isLarge()` implementation
- `src/character.cpp` — `PEEK_TOP` const → `peekTop()` static helper; ~10 call-site updates
- `src/buddy.cpp` — `BUDDY_CANVAS_W` const → `buddyCanvasW()` static helper (or similar); call-site updates
- `src/buddy_common.h` — if `BUDDY_CANVAS_W` is declared here as a shared constant, replace with helper or extern function
- `src/screens/stats.cpp` — sprite radii + Lv badge size + label-size bumps
- `src/screens/info.cpp` — text size + line spacing bumps
- `src/screens/passkey.cpp` — passkey digit size bump
- `src/screens/approval.cpp` — header + button-hint size bumps
- `src/screens/menu.cpp` — item text size bump
- `src/screens/settings.cpp` — no font change (item count too high), but row pitch adjustment if the layout has y-spacing logic worth tuning
- `src/screens/reset.cpp` — item text size bump
- `src/screens/hud.cpp` — text size + line height bump

**Unchanged**: `platformio.ini`, `ble_bridge.*`, `data.h`, `xfer.h`, `stats.h`, `input.h`, all `buddies/*.cpp`, `screens/clock.cpp`.

## Migration sequence

Single commit. ~13 files modified. Every change is gated by `hal::display::isLarge()` so StickC paths are unchanged.

### Task 1 — Add helper + per-screen adaptations

1. Add `isLarge()` to `src/hal/display.{h,cpp}`.
2. Convert `PEEK_TOP` in `character.cpp` to a `static int peekTop()` helper that returns 100 when `hal::display::isLarge()` else 70. Update arithmetic call sites.
3. Same treatment for `BUDDY_CANVAS_W` in `buddy.cpp` (and `buddy_common.h` if it's the canonical declaration).
4. Per-screen adaptations per the table above. Each screen gets its `setTextSize(...)` and sprite-radius constants gated by `hal::display::isLarge()`.
5. Build both envs.
6. Commit with message `Phase B.3: Core2 landscape layout adaptations`.

**Total: 1 commit.**

## Validation / acceptance

### Code-level invariants

```bash
# Both envs build clean
/Users/stephenoliver/.platformio/penv/bin/pio run -e m5stickc-plus
/Users/stephenoliver/.platformio/penv/bin/pio run -e m5stack-core2

# isLarge() helper exists and is used
grep -n "isLarge" src/hal/display.h src/hal/display.cpp     # 2 hits
grep -rn "hal::display::isLarge\|isLarge()" src/screens src/character.cpp src/buddy.cpp
                                                            # multiple hits expected

# PEEK_TOP / BUDDY_CANVAS_W converted to functions
grep -n "PEEK_TOP" src/character.cpp                        # only the function definition
grep -n "BUDDY_CANVAS_W" src/buddy.cpp src/buddy_common.h   # only the function definition
```

### StickC equivalence

Since `isLarge()` returns `false` on StickC, every adaptation branch falls through to the original code path. Functional equivalence on StickC is preserved by construction.

### Core2 visual outcome

After flash, Core2 should show:
- Buddy ASCII art rendered in a taller (~100 px) and wider (~160 px canvas) top band
- Stats indicators (hearts, dots, bars) larger and spread across the full 320 px
- Info screen text readable at size-2 instead of cramped size-1
- Passkey digits prominent at ~1.5x the StickC size
- Approval and menu / reset use size-3 primary text
- HUD message scroll readable at size-2

Verification is by user flash + eyeball, not a hard gate.

### NVS preservation

Unchanged. Partition layout (`no_ota.csv`) is identical. NVS at `0x9000–0xdfff` untouched on flash.

### Acceptance

Both builds green + grep checks confirm `isLarge()` is wired = done.
