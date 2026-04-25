# Phase B.3 — Core2 Landscape Layout Adaptations Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Adapt all screens, the character region, and the buddy ASCII canvas so they fit Core2's 320×240 landscape display with appropriately-sized fonts and sprites, while keeping StickC's behavior byte-for-byte equivalent.

**Architecture:** Add a single `hal::display::isLarge()` predicate that returns `true` when display width ≥ 320 (Core2-class) and `false` otherwise (StickC-class). Each screen and the character/buddy renderers branch on `isLarge()` at the relevant draw sites — text sizes, sprite radii, line spacing, and the character region height all scale up on Core2 while StickC paths stay identical.

**Tech Stack:** PlatformIO, Arduino, ESP32, M5Unified, M5GFX/LovyanGFX, NimBLE-Arduino.

**Verification model:** Code-level only (per project policy). Both envs build clean; greps confirm `isLarge()` is wired through expected files. No on-device walkthrough required — user flashes and visually confirms separately.

**Spec reference:** `docs/superpowers/specs/2026-04-25-phase-b3-core2-layouts-design.md`

**Build commands:**
```bash
/Users/stephenoliver/.platformio/penv/bin/pio run -e m5stickc-plus
/Users/stephenoliver/.platformio/penv/bin/pio run -e m5stack-core2
```

---

## Files to Touch

- `src/hal/display.h`, `src/hal/display.cpp` — add `isLarge()` helper
- `src/character.cpp` — convert `PEEK_TOP` const to `peekTop()` runtime helper
- `src/buddy.cpp`, `src/buddy_common.h` — convert `BUDDY_CANVAS_W` extern const to `buddyCanvasW()` runtime helper
- `src/screens/stats.cpp` — sprite radii + Lv badge size
- `src/screens/info.cpp` — text size + line spacing
- `src/screens/passkey.cpp` — passkey digit size
- `src/screens/approval.cpp` — header + button-hint sizes
- `src/screens/menu.cpp` — item text size
- `src/screens/reset.cpp` — item text size
- `src/screens/hud.cpp` — text size + line height

**Unchanged:** `screens/clock.cpp` (clock disabled), `screens/settings.cpp` (10-item list doesn't fit at size-3), `platformio.ini`, BLE / data / xfer / stats data layer, `buddies/*.cpp`.

---

## Task 1 — Add `hal::display::isLarge()` helper

**Files:** `src/hal/display.h`, `src/hal/display.cpp`

- [ ] **Step 1: Read current `src/hal/display.h`**

Confirm the current namespace structure. Use `Read`.

- [ ] **Step 2: Add `isLarge()` declaration**

Use `Edit`. Find:

```cpp
  void push();                     // sprite → LCD
}}
```

Replace with:

```cpp
  void push();                     // sprite → LCD
  bool isLarge();                  // true when display width ≥ 320 (Core2-class)
}}
```

- [ ] **Step 3: Add `isLarge()` implementation in `src/hal/display.cpp`**

Use `Edit`. Find:

```cpp
void push()                  { _spr.pushSprite(&M5.Display, 0, 0); }
```

Replace with:

```cpp
void push()                  { _spr.pushSprite(&M5.Display, 0, 0); }
bool isLarge()               { return M5.Display.width() >= 320; }
```

(If the actual `push()` line is different — e.g., different formatting — adjust the `old_string` to match exactly.)

- [ ] **Step 4: Build both envs**

```bash
/Users/stephenoliver/.platformio/penv/bin/pio run -e m5stickc-plus
/Users/stephenoliver/.platformio/penv/bin/pio run -e m5stack-core2
```

Expected: both SUCCESS.

- [ ] **Step 5: Don't commit yet** — accumulate changes; commit at end of Task 11.

---

## Task 2 — Convert `PEEK_TOP` to `peekTop()` runtime helper

**File:** `src/character.cpp`

The current declaration (line 43): `static const int PEEK_TOP = 70;`. Used at:
- Line 54: `gifY = peekMode ? (PEEK_TOP - outH) / 2 : (140 - outH) / 2;`
- Line 120: `if (y < 0 || y >= PEEK_TOP) return;`

Both uses are runtime (no constant-expression context). Safe to convert to a function.

- [ ] **Step 1: Add include for `hal/display.h` if not present**

Read top of `src/character.cpp`. Use `Read`. If `#include "hal/display.h"` is already present, skip; otherwise add it grouped with other project includes.

- [ ] **Step 2: Replace the constant with a helper**

Use `Edit`. Find:

```cpp
static const int   PEEK_TOP = 70;
```

Replace with:

```cpp
// Vertical extent of the character region. Core2-class screens (320 wide)
// give the buddy a taller band; StickC-class stays at 70.
static int peekTop() { return hal::display::isLarge() ? 100 : 70; }
```

(Match the original whitespace: the spaces between `int` and `PEEK_TOP` exist in the source — use a unique substring or include enough surrounding context for the Edit to match.)

- [ ] **Step 3: Update first call site (~line 54)**

Use `Edit`. Find:

```cpp
  gifY = peekMode ? (PEEK_TOP - outH) / 2 : (140 - outH) / 2;
```

Replace:

```cpp
  gifY = peekMode ? (peekTop() - outH) / 2 : (140 - outH) / 2;
```

- [ ] **Step 4: Update second call site (~line 120)**

Use `Edit`. Find:

```cpp
    if (y < 0 || y >= PEEK_TOP) return;
```

Replace:

```cpp
    if (y < 0 || y >= peekTop()) return;
```

- [ ] **Step 5: Verify no more PEEK_TOP references**

```bash
grep -n "PEEK_TOP" src/character.cpp
```

Expected: zero matches.

- [ ] **Step 6: Build both envs**

```bash
/Users/stephenoliver/.platformio/penv/bin/pio run -e m5stickc-plus
/Users/stephenoliver/.platformio/penv/bin/pio run -e m5stack-core2
```

Expected: both SUCCESS.

---

## Task 3 — Convert `BUDDY_CANVAS_W` to `buddyCanvasW()` runtime helper

**Files:** `src/buddy.cpp`, `src/buddy_common.h`

`buddy_common.h:10` declares `extern const int BUDDY_CANVAS_W;`. Defined at `buddy.cpp:13` as `const int BUDDY_CANVAS_W = 135;`. Used at `buddy.cpp:191` in a `fillRect` call.

- [ ] **Step 1: Update the header**

Use `Edit` on `src/buddy_common.h`. Find:

```cpp
extern const int BUDDY_CANVAS_W;
```

Replace:

```cpp
int buddyCanvasW();   // canvas width: 240 on Core2-class screens, 135 on StickC
```

- [ ] **Step 2: Replace the definition in `src/buddy.cpp`**

Use `Edit`. Find:

```cpp
const int BUDDY_CANVAS_W = 135;
```

Replace:

```cpp
int buddyCanvasW() { return hal::display::isLarge() ? 240 : 135; }
```

- [ ] **Step 3: Add `#include "hal/display.h"` to `src/buddy.cpp` if not present**

Read top of file with `Read`. If the include isn't there yet, add it grouped with other project includes.

- [ ] **Step 4: Update the call site (~line 191)**

Use `Read` to see the exact current line:

```bash
grep -n "BUDDY_CANVAS_W" src/buddy.cpp
```

The line should look like:

```cpp
  canvas.fillRect(0, 0, BUDDY_CANVAS_W,
```

Use `Edit`. Find that line plus enough surrounding context for uniqueness, and replace `BUDDY_CANVAS_W` with `buddyCanvasW()`.

- [ ] **Step 5: Verify no more references**

```bash
grep -rn "BUDDY_CANVAS_W" src/
```

Expected: zero matches.

- [ ] **Step 6: Build both envs**

```bash
/Users/stephenoliver/.platformio/penv/bin/pio run -e m5stickc-plus
/Users/stephenoliver/.platformio/penv/bin/pio run -e m5stack-core2
```

Expected: both SUCCESS.

---

## Task 4 — Adapt stats screen sprite sizes

**File:** `src/screens/stats.cpp`

Bump heart radius, fed dot radius, and energy bar dimensions on `isLarge()`. Lv badge gets a wider rect and bigger inner text size. Grid values and labels stay size-2 (recently tuned by user; don't disturb).

- [ ] **Step 1: Add `hal/display.h` include if not present**

Read top of file. If `#include "../hal/display.h"` isn't there, add it next to other hal includes.

- [ ] **Step 2: Update `tinyHeart()` to scale**

Use `Read` on the function (around line 34). The current implementation uses radius 4, triangle from `(x-8, y+2)` to `(x+8, y+2)` to `(x, y+10)`.

Use `Edit`. Find:

```cpp
static void tinyHeart(int x, int y, bool filled, uint16_t col) {
  if (filled) {
    canvas.fillCircle(x - 4, y, 4, col);
    canvas.fillCircle(x + 4, y, 4, col);
    canvas.fillTriangle(x - 8, y + 2, x + 8, y + 2, x, y + 10, col);
  } else {
    canvas.drawCircle(x - 4, y, 4, col);
    canvas.drawCircle(x + 4, y, 4, col);
    canvas.drawLine(x - 8, y + 2, x, y + 10, col);
    canvas.drawLine(x + 8, y + 2, x, y + 10, col);
  }
}
```

Replace:

```cpp
static void tinyHeart(int x, int y, bool filled, uint16_t col) {
  const int r = hal::display::isLarge() ? 6 : 4;
  if (filled) {
    canvas.fillCircle(x - r, y, r, col);
    canvas.fillCircle(x + r, y, r, col);
    canvas.fillTriangle(x - 2*r, y + r/2, x + 2*r, y + r/2, x, y + 2*r + r/2, col);
  } else {
    canvas.drawCircle(x - r, y, r, col);
    canvas.drawCircle(x + r, y, r, col);
    canvas.drawLine(x - 2*r, y + r/2, x, y + 2*r + r/2, col);
    canvas.drawLine(x + 2*r, y + r/2, x, y + 2*r + r/2, col);
  }
}
```

(Geometry: the original used radius-4 circles centered at ±4, with a triangle base at y+2 (half-radius down) and tip at y+10 (~2.5×r below the circle centers). The new code uses `r` everywhere with the same proportional geometry.)

- [ ] **Step 3: Update fed dots**

Use `Read` to find the fed-dots loop. It looks like:

```cpp
  for (int i = 0; i < 10; i++) {
    int cx = (W * (2 * i + 1)) / 20;
    if (i < fed) canvas.fillCircle(cx, 108, 4, p.body);
    else         canvas.drawCircle(cx, 108, 4, p.textDim);
  }
```

Use `Edit`. Replace the body to use a parametric radius:

```cpp
  const int dotR = hal::display::isLarge() ? 5 : 4;
  for (int i = 0; i < 10; i++) {
    int cx = (W * (2 * i + 1)) / 20;
    if (i < fed) canvas.fillCircle(cx, 108, dotR, p.body);
    else         canvas.drawCircle(cx, 108, dotR, p.textDim);
  }
```

(If the surrounding code already declares a different `dotR` or uses different spacing, adjust to match.)

- [ ] **Step 4: Update energy bars**

Find:

```cpp
  for (int i = 0; i < 5; i++) {
    int cx = (W * (2 * i + 1)) / 10;
    if (i < en) canvas.fillRect(cx - 7, 122, 15, 10, enCol);
    else        canvas.drawRect(cx - 7, 122, 15, 10, p.textDim);
  }
```

Replace:

```cpp
  const int barW = hal::display::isLarge() ? 22 : 15;
  const int barH = hal::display::isLarge() ? 14 : 10;
  for (int i = 0; i < 5; i++) {
    int cx = (W * (2 * i + 1)) / 10;
    if (i < en) canvas.fillRect(cx - barW/2, 122, barW, barH, enCol);
    else        canvas.drawRect(cx - barW/2, 122, barW, barH, p.textDim);
  }
```

- [ ] **Step 5: Update Lv badge**

Find:

```cpp
  canvas.fillRoundRect(6, y - 2, 42, 14, 3, p.body);
  canvas.setTextColor(p.bg, p.body);
  canvas.setCursor(11, y + 1); canvas.printf("Lv %u", stats().level);
```

Replace:

```cpp
  const int lvW = hal::display::isLarge() ? 60 : 42;
  const int lvH = hal::display::isLarge() ? 18 : 14;
  canvas.fillRoundRect(6, y - 2, lvW, lvH, 3, p.body);
  canvas.setTextColor(p.bg, p.body);
  canvas.setTextSize(hal::display::isLarge() ? 2 : 1);
  canvas.setCursor(11, y + 1); canvas.printf("Lv %u", stats().level);
  canvas.setTextSize(1);
```

(Trailing `setTextSize(1)` resets to size-1 in case downstream code expects it. If the Lv block is followed immediately by another `setTextSize` call, the reset is redundant but harmless.)

- [ ] **Step 6: Build both envs**

```bash
/Users/stephenoliver/.platformio/penv/bin/pio run -e m5stickc-plus
/Users/stephenoliver/.platformio/penv/bin/pio run -e m5stack-core2
```

Expected: both SUCCESS.

---

## Task 5 — Adapt info screen text size

**File:** `src/screens/info.cpp`

Multiple `setTextSize(1)` and `setTextSize(2)` calls. Bump them on `isLarge()`.

- [ ] **Step 1: Add `hal/display.h` include if not present**

Read top of file.

- [ ] **Step 2: Identify text-size sites**

Run:

```bash
grep -n "setTextSize\|.setCursor\|.print\|line height\|y +=" src/screens/info.cpp | head -30
```

Note all `setTextSize(1)` calls — these are the ones that bump to `setTextSize(2)` on large.

- [ ] **Step 3: Replace each `setTextSize(1)` with conditional**

For each occurrence, use `Edit` to change:

```cpp
canvas.setTextSize(1);
```

to:

```cpp
canvas.setTextSize(hal::display::isLarge() ? 2 : 1);
```

If multiple identical lines exist with the exact same surrounding context, use `replace_all: true` on a single Edit. If they have different context, do them individually.

- [ ] **Step 4: Replace `setTextSize(2)` calls (header rows)**

Same pattern, but bumping size 2 → 3 on large:

```cpp
canvas.setTextSize(2);
```

becomes:

```cpp
canvas.setTextSize(hal::display::isLarge() ? 3 : 2);
```

- [ ] **Step 5: Adjust line spacing**

Look for explicit `y += N` patterns advancing the cursor between lines. Bump them on large to accommodate larger text:

```cpp
y += 9;   // size-1 line height was 8 + 1
```

becomes:

```cpp
y += hal::display::isLarge() ? 16 : 9;
```

Similarly any `y += 12` for size-2 contexts becomes `y += hal::display::isLarge() ? 22 : 12`.

(Walk through each `y +=` site and decide. Don't blanket-replace — some y advances are between sections, not between text lines, and shouldn't change.)

- [ ] **Step 6: Build both envs**

```bash
/Users/stephenoliver/.platformio/penv/bin/pio run -e m5stickc-plus
/Users/stephenoliver/.platformio/penv/bin/pio run -e m5stack-core2
```

Expected: both SUCCESS.

---

## Task 6 — Adapt passkey screen

**File:** `src/screens/passkey.cpp`

Single passkey display screen. The 6-digit number is the focus.

- [ ] **Step 1: Read current draw**

Use `Read` to see the current text-size and y-position used for the passkey digits.

- [ ] **Step 2: Bump font size**

Find the `canvas.setTextSize(N)` line that immediately precedes the passkey draw (likely the largest setTextSize in the file — value 3 or 4). Wrap it:

```cpp
canvas.setTextSize(N);
```

becomes:

```cpp
canvas.setTextSize(hal::display::isLarge() ? N + 2 : N);
```

(If N=4 originally, it becomes 6 on large; if N=3, it becomes 5.)

If a centered y-position uses a fixed value relative to height, leave it — `M5.Display.height()` is the same on both boards. Only horizontal/scale changes are needed.

- [ ] **Step 3: Add `hal/display.h` include if not present**

- [ ] **Step 4: Build both envs**

Expected: both SUCCESS.

---

## Task 7 — Adapt approval screen

**File:** `src/screens/approval.cpp`

Bump the "approve?" header to size-3 and button hint text to size-2 on large.

- [ ] **Step 1: Find text-size sites**

```bash
grep -n "setTextSize" src/screens/approval.cpp
```

- [ ] **Step 2: For each `setTextSize(2)` that's a header**, change to `hal::display::isLarge() ? 3 : 2`.

- [ ] **Step 3: For each `setTextSize(1)` that's a button hint**, change to `hal::display::isLarge() ? 2 : 1`.

- [ ] **Step 4: Add include if needed; build both envs**

---

## Task 8 — Adapt menu and reset screens

**Files:** `src/screens/menu.cpp`, `src/screens/reset.cpp`

Both are short item lists. Bump item text size 2 → 3 on large.

- [ ] **Step 1: For each file**, find the `setTextSize` calls and the row-pitch math.

- [ ] **Step 2: Bump text size**

Find `canvas.setTextSize(2)` (the item rendering text) and replace with `canvas.setTextSize(hal::display::isLarge() ? 3 : 2)`.

- [ ] **Step 3: Bump row pitch**

Find the y-advance per item (commonly `y += 18` or similar). Bump on large:

```cpp
y += 18;
```

becomes:

```cpp
y += hal::display::isLarge() ? 26 : 18;
```

(Adjust the actual numbers based on what the file has.)

- [ ] **Step 4: Add include if needed; build both envs**

**Note: `screens/settings.cpp` is NOT changed** — it has 10 items, and 10 × size-3 row pitch (~26 px each = 260 px total) exceeds the 240 px screen height. Settings stays size-2.

---

## Task 9 — Adapt HUD screen

**File:** `src/screens/hud.cpp`

The bottom message scroll. Currently size-1, line height 8.

- [ ] **Step 1: Find the constants**

The HUD has constants like `LH = 8` (line height) and likely `SHOW = 3` (visible lines). Read the file.

- [ ] **Step 2: Make line-height conditional**

Find:

```cpp
const int SHOW = 3, LH = 8, WIDTH = 21;
```

(or similar). Convert `LH` to depend on `isLarge()`:

```cpp
const int SHOW = 3;
const int LH = hal::display::isLarge() ? 16 : 8;
const int WIDTH = hal::display::isLarge() ? 13 : 21;
```

(Width is in characters; size-2 chars are 12 px wide vs 6 for size-1, so display-width / char-width gives the new wrap column. Adjust based on actual values.)

- [ ] **Step 3: Bump text size**

Find `canvas.setTextSize(1)` in the file and replace with `canvas.setTextSize(hal::display::isLarge() ? 2 : 1)`.

- [ ] **Step 4: Add include if needed; build both envs**

---

## Task 10 — Adapt clock screen (minimal)

**File:** `src/screens/clock.cpp`

Per the spec: clock is currently disabled (`bool clocking = false`). Skip detailed adaptation; the existing landscape-mode draw path will work on Core2 by default. **No changes in this task** — but list it explicitly so the reviewer doesn't think it was missed.

- [ ] **Step 1: Verify clock is still disabled in main.cpp**

```bash
grep -n "bool clocking" src/main.cpp
```

Expected: shows `bool clocking = false;` (the hard-disable from earlier work).

- [ ] **Step 2: No code changes** — proceed to Task 11.

---

## Task 11 — Final build, verify invariants, commit

- [ ] **Step 1: Final clean build of both envs**

```bash
/Users/stephenoliver/.platformio/penv/bin/pio run -e m5stickc-plus
/Users/stephenoliver/.platformio/penv/bin/pio run -e m5stack-core2
```

Both must SUCCESS.

- [ ] **Step 2: Verify code-level invariants**

```bash
# isLarge() is declared and used
grep -n "isLarge" src/hal/display.h src/hal/display.cpp     # 2 hits

# Multiple consumers
grep -rn "hal::display::isLarge\|isLarge()" src/screens src/character.cpp src/buddy.cpp
                                                            # at least 8 call sites expected

# Old constants gone
grep -rn "PEEK_TOP" src/                                    # only the helper function definition
grep -rn "BUDDY_CANVAS_W" src/                              # only the helper function definition
```

- [ ] **Step 3: Commit**

```bash
git add src/
git commit -m "Phase B.3: Core2 landscape layout adaptations"
```

Verify:

```bash
git log --oneline -3
git status
```

Expected: one new commit on `hal-refactor`, working tree clean.

---

## Completion checklist

- [ ] `pio run -e m5stickc-plus` SUCCESS.
- [ ] `pio run -e m5stack-core2` SUCCESS.
- [ ] `grep -n "isLarge" src/hal/display.h src/hal/display.cpp` shows two matches.
- [ ] `grep -rn "isLarge()" src/screens src/character.cpp src/buddy.cpp` shows ≥8 call sites.
- [ ] `grep -rn "PEEK_TOP" src/` matches only the helper function definition (no bare references).
- [ ] `grep -rn "BUDDY_CANVAS_W" src/` matches only the helper function definition.
- [ ] One new commit on `hal-refactor` with message `Phase B.3: Core2 landscape layout adaptations`.

Phase B.3 is complete. The Phase B trilogy (B.1 M5Unified, B.2 Core2 build target, B.3 Core2 layouts) is finished.
