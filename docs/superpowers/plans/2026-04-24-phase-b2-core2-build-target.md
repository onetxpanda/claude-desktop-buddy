# Phase B.2 — Core2 Build Target Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `m5stack-core2` as a second PlatformIO build target sharing the existing source tree, with HAL display dimensions made parametric so the same code runs unchanged on StickC Plus and Core2.

**Architecture:** One commit, two files modified. `platformio.ini` gains a second env block with `board = m5stack-core2`; `src/hal/display.cpp` replaces four hardcoded dimension/rotation literals with runtime calls to M5Unified. M5Unified abstracts all other board differences — screens, buddies, and the rest of the HAL are unchanged.

**Tech Stack:** PlatformIO, Arduino, ESP32, M5Unified (covers both boards).

**Verification model:** No tests, no on-device walkthrough. Acceptance is `pio run -e m5stickc-plus` + `pio run -e m5stack-core2` both exiting 0, plus one grep invariant.

**Spec reference:** `docs/superpowers/specs/2026-04-24-phase-b2-core2-build-target-design.md`

**Build commands:**
```bash
/Users/stephenoliver/.platformio/penv/bin/pio run -e m5stickc-plus
/Users/stephenoliver/.platformio/penv/bin/pio run -e m5stack-core2
```

---

## Task 1 — Add Core2 env and parameterize HAL display

**Files modified (2):**
- `platformio.ini`
- `src/hal/display.cpp`

**Files unchanged:** everything else in `src/`, spec, plan, partition table, etc.

---

- [ ] **Step 1 — Edit `platformio.ini`: append the Core2 env**

Read the file to confirm the existing env block structure, then use `Edit` to append the new env block at the end (leaving the existing `[env:m5stickc-plus]` block untouched).

`old_string` (to anchor the edit at the end of the StickC env block; use the last line of the file plus a trailing newline):

```
    bblanchon/ArduinoJson @ ^7.0.0
```

`new_string`:

```
    bblanchon/ArduinoJson @ ^7.0.0

[env:m5stack-core2]
platform = espressif32
board = m5stack-core2
framework = arduino
monitor_speed = 115200
board_build.filesystem = littlefs
board_build.partitions = no_ota.csv
build_flags =
    -DCORE_DEBUG_LEVEL=0
build_src_filter = +<*> +<buddies/>
lib_deps =
    m5stack/M5Unified
    bitbank2/AnimatedGIF @ ^2.1.1
    bblanchon/ArduinoJson @ ^7.0.0
```

If the `old_string` isn't unique (unlikely — `bblanchon/ArduinoJson @ ^7.0.0` should appear only once), include more preceding context to disambiguate.

Note: Core2 env deliberately omits `board_build.f_cpu = 160000000L` — let the board default (240 MHz) apply.

---

- [ ] **Step 2 — Edit `src/hal/display.cpp`: remove hardcoded rotation**

Read the file first. The current body of `begin()` is:

```cpp
void begin() {
  M5.Display.setRotation(0);
  _spr.createSprite(135, 240);
}
```

Use `Edit` with:

`old_string`:

```cpp
void begin() {
  M5.Display.setRotation(0);
  _spr.createSprite(135, 240);
}
```

`new_string`:

```cpp
void begin() {
  _spr.createSprite(M5.Display.width(), M5.Display.height());
}
```

---

- [ ] **Step 3 — Edit `src/hal/display.cpp`: parametric `width()`**

Use `Edit`:

`old_string`: `int  width()                 { return 135; }`

`new_string`: `int  width()                 { return M5.Display.width(); }`

---

- [ ] **Step 4 — Edit `src/hal/display.cpp`: parametric `height()`**

Use `Edit`:

`old_string`: `int  height()                { return 240; }`

`new_string`: `int  height()                { return M5.Display.height(); }`

---

- [ ] **Step 5 — Build StickC env**

```bash
/Users/stephenoliver/.platformio/penv/bin/pio run -e m5stickc-plus
```

Expected: `SUCCESS`. This is the regression check — if this fails, something in the parametric dimension edits broke StickC.

---

- [ ] **Step 6 — Build Core2 env**

```bash
/Users/stephenoliver/.platformio/penv/bin/pio run -e m5stack-core2
```

Expected: `SUCCESS`.

Possible first-run issues:
- Platform toolchain not installed for Core2: PlatformIO auto-downloads. First run may take several minutes while it fetches the framework for the `m5stack-core2` board definition.
- Library dependency conflict: `m5stack/M5Unified` is already cached from Phase B.1, so no new download expected.

If build fails, read the error. Common causes:
- A hardcoded `135` or `240` still lurking in `src/hal/` — grep (Step 7) will confirm.
- A compile-time constant somewhere else in the code assuming StickC dimensions. This is a real issue to report; it shouldn't exist if Phase B.1 was correctly implemented.

---

- [ ] **Step 7 — Verify code-level invariant**

```bash
grep -rn "\b135\b\|\b240\b" src/hal/
```

Expected: zero non-comment matches. (Comment lines like `// 135 on StickC` if any exist can remain; the test is on executable code.)

If any hardcoded matches appear, update the file to use `M5.Display.width()` or `M5.Display.height()` as appropriate, then re-run Steps 5-6.

---

- [ ] **Step 8 — Commit**

```bash
git add platformio.ini src/hal/display.cpp
git commit -m "Add m5stack-core2 env; parametric display dims"
```

Verify:

```bash
git log --oneline -3
git status
```

Status should show "nothing to commit, working tree clean". Log should show the new commit on top of `hal-refactor`.

---

## Completion checklist

After Task 1 completes:

- [ ] `pio run -e m5stickc-plus` exits 0 (StickC unchanged).
- [ ] `pio run -e m5stack-core2` exits 0 (Core2 builds).
- [ ] `grep -rn "\b135\b\|\b240\b" src/hal/` returns zero non-comment matches.
- [ ] One new commit on `hal-refactor` with message `Add m5stack-core2 env; parametric display dims`.

Phase B.2 is complete. Phase B.3 (Core2 landscape layouts) is a separate spec + plan.
