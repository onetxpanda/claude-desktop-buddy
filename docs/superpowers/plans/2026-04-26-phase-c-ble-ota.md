# Phase C — BLE-driven OTA Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** End-to-end BLE OTA: `claude-buddy update` (or auto-prompt) downloads the matching board's `firmware.bin` from the GitHub Releases `latest` tag and pushes it to the paired device over the existing NUS UART link. Device writes to the inactive OTA slot via `Update.h`, verifies the SHA-256, sets the boot partition, and reboots. NVS, BLE bonds, and LittleFS contents survive every update after the one-time partition migration.

**Architecture:** Partition table swap (`no_ota.csv` → `partitions_ota.csv`, two 1.25 MB OTA slots, 1.4 MB LittleFS); device-side `ota.cpp` state machine driven by `cmd:ota_*` JSON lines on the existing TX/RX characteristics; bridge-side `ota.py` chunker + `release.py` GitHub poller; `screens/ota.cpp` for the on-device progress bar; one-line auto-rollback hook in `setup()`.

**Tech Stack:** PlatformIO, Arduino-ESP32 v2, M5Unified, M5GFX, NimBLE-Arduino, ESP-IDF `Update.h` / `esp_ota_ops.h`, Python 3.11+ with `bleak`, GitHub Actions.

**Verification model:** Mixed. Code-level for the firmware build (size fits, both envs compile clean). Bridge has unit tests for `ota.py` chunking and `release.py` polling. End-to-end flow requires real hardware — call out the manual test steps but don't block plan completion on them.

**Spec reference:** `docs/superpowers/specs/2026-04-26-phase-c-ble-ota-design.md`

**Build commands:**
```bash
pio run -e m5stickc-plus
pio run -e m5stack-core2
cd bridge && pixi run pytest
```

---

## Files to Touch

**Firmware:**
- `partitions_ota.csv` (new) — partition table
- `platformio.ini` — switch both ESP32 envs to the new partition table; add `-DBUILD_VERSION` flag wired from CI
- `src/ota.h`, `src/ota.cpp` (new) — state machine, `Update.h` glue
- `src/ble_bridge.cpp` — route `cmd:ota_*` JSON to `ota::handle_command`
- `src/screens/ota.h`, `src/screens/ota.cpp` (new) — full-screen progress bar
- `src/main.cpp` — `esp_ota_mark_app_valid_cancel_rollback_after(30000)` in setup; loop short-circuits to OTA screen when state ≠ IDLE; emit `info` event on connect
- `src/data.h` — extend with OTA shapes (so JSON parsing stays in one place)

**Bridge:**
- `bridge/src/claude_buddy_bridge/ota.py` (new) — protocol layer + chunker
- `bridge/src/claude_buddy_bridge/release.py` (new) — GitHub Releases polling
- `bridge/src/claude_buddy_bridge/protocol.py` — add OTA dataclasses
- `bridge/src/claude_buddy_bridge/cli.py` — `update` subcommand
- `bridge/src/claude_buddy_bridge/daemon.py` — wire release poller; `auto_update` config
- `bridge/tests/test_ota.py`, `bridge/tests/test_release.py` (new) — unit tests

**CI:**
- `.github/workflows/screenshots.yml` — add a `bridge` job (pixi + pytest); pass `-DBUILD_VERSION="${branch}@${sha}"` into firmware build steps

---

## Step 1 — Verify firmware fits in 1.25 MB app slot

Don't write the partition table file yet — first see whether the firmware as it stands today fits. If it overflows, the recovery order is: shrink LittleFS first, fonts only as a fallback (per spec).

- [ ] Create a throwaway local file `partitions_ota_probe.csv` with the layout from the spec
- [ ] In `[env:m5stack-core2]`, temporarily change `board_build.partitions = partitions_ota_probe.csv`
- [ ] Run `pio run -e m5stack-core2 -v 2>&1 | grep -E "Flash:|RAM:|app0|app1"`. Capture the percentages.
- [ ] If `Flash: [=========> ]  N% (used X bytes from Y bytes)` shows N ≥ 95% — overflow risk. Drop the LittleFS partition from 0x170000 (1.4 MB) to 0x0E0000 (0.9 MB), bump app0 and app1 sizes by 0x40000 (256 KB) each. Re-test.
- [ ] If still overflowing after LittleFS shrink, document by how much and consider M5GFX font subset trimming (separate decision — note in the spec, don't actually do it as part of this plan).
- [ ] Repeat for `m5stickc-plus`.
- [ ] Delete the probe CSV; record the final partition layout in step 2.

**Output of this step:** known-good partition layout (either the spec's defaults or with LittleFS shrunk).

---

## Step 2 — Land the partition table change

- [ ] Write `partitions_ota.csv` at the repo root with the final layout from step 1
- [ ] Update `platformio.ini`: both `[env:m5stickc-plus]` and `[env:m5stack-core2]` get `board_build.partitions = partitions_ota.csv`
- [ ] `pio run -e m5stickc-plus -e m5stack-core2` — both build clean
- [ ] Commit. Test plan in commit body: this commit alone is unsafe to flash to existing devices without erase — note that flashing requires `esptool.py erase_flash` once, after which uploads are normal.

---

## Step 3 — Wire BUILD_VERSION end-to-end

So the device knows what it's running and can report it. Sent as `ack:info` on connect, NOT a new `evt:` (would crash older bridges per the backward-compat rule).

- [ ] Update `.github/workflows/screenshots.yml`'s "Build firmware" step to inject `-DBUILD_VERSION="\"${branch}@${sha}\""` (note the quoting — the C define needs a quoted string literal)
- [ ] Add a header `src/version.h` with `extern const char* BUILD_VERSION;`
- [ ] Add a small `src/version.cpp` that defines `const char* BUILD_VERSION = BUILD_VERSION_DEFINE` (using a fallback `"dev-local"` when the define is absent)
- [ ] In `main.cpp`'s BLE-connected handler, send once: `{"ack":"info","ok":true,"data":{"board":"<env>","version":"<BUILD_VERSION>","features":["ota_v1","xfer_v1"]}}`. Board name comes from build-time `-DARDUINO_M5STACK_Core2` / `-DARDUINO_M5Stick_C` defines (existing in board JSONs).
- [ ] Build both envs, confirm `BUILD_VERSION` resolves: `xtensa-esp32-elf-strings .pio/build/m5stack-core2/firmware.elf | grep -E '^[a-z-]+@[a-f0-9]{7}'`

---

## Step 4 — Device-side OTA state machine (happy path, no UI yet)

**Backward-compat note**: per the spec, all device → bridge OTA notifications use the existing `ack:NAME` shape (not `evt:`) so older bridges parse them as generic `Ack`s and don't crash. All four `cmd:ota_*` are dispatched in `_applyJson` *before* `xferCommand(doc)` so older devices (without OTA) silently swallow them via xfer's catch-all.

- [ ] Create `src/ota.h` with the public API:
  ```cpp
  namespace ota {
    enum class State { Idle, Receiving, Committing, Error };
    State state();
    size_t received(); size_t total();
    const char* error_msg();
    // Returns true if the cmd was an ota_* and was handled. Caller (in
    // _applyJson) should short-circuit before xferCommand() if true.
    bool handle_command(JsonDocument& doc);
    // Called from main.cpp loop(); drains pending ack:ota_* messages.
    bool poll_event(char* out, size_t cap);
  }
  ```
- [ ] Implement `src/ota.cpp` using `Update.h`. State transitions:
  - `Idle` + `cmd:ota_begin` → call `Update.begin(size, U_FLASH)`. On success: store SHA, version, total; emit `ack:ota_begin {ok:true}`; transition to `Receiving`. On failure: emit `ack:ota_begin {ok:false, error:"..."}`.
  - `Receiving` + `cmd:ota_data` (with expected `seq`): base64-decode `b64`, call `Update.write(buf, len)`, update running SHA. Emit `ack:ota_data {ok:true, n:seq}` every 32 chunks. Emit `ack:ota_progress {ok:true, n:pct}` every 64 chunks (rough 1% granularity).
  - `Receiving` + `cmd:ota_data` (wrong `seq`): emit `ack:ota_data {ok:false, error:"seq mismatch", n:expected}` and `Update.abort()`; state goes Error.
  - `Receiving` + `cmd:ota_commit`: compare running SHA to expected; if mismatch, emit `ack:ota_commit {ok:false, error:"sha mismatch"}` and abort. If match, call `Update.end(true)` to set boot partition; emit `ack:ota_commit {ok:true}`; schedule `ESP.restart()` after a 200 ms grace period to let the notify drain.
  - Any state + `cmd:ota_abort` → `Update.abort()`, emit `ack:ota_abort {ok:true}`, back to Idle.
- [ ] Hook into `src/ble_bridge.cpp` (or wherever `_applyJson` lives): call `ota::handle_command(doc)` BEFORE `xferCommand(doc)` and return early if it consumed.
- [ ] Hook into `src/main.cpp` loop: drain `ota::poll_event` and send via the existing `bleWrite()` path.
- [ ] Build both envs.

---

## Step 5 — Bridge-side `ota.py` (protocol layer)

**Backward-compat note**: device-side messages all arrive as `Ack(ack="ota_*", ok=..., n=..., error=..., data=...)` via the existing `decode_device_line` parser — no parser changes needed. The bridge only adds OTA-specific *interpretation* of those Ack messages.

- [ ] Add OTA host-command dataclasses to `bridge/src/claude_buddy_bridge/protocol.py`: `OtaBegin`, `OtaData`, `OtaCommit`, `OtaAbort`. Each builds a `cmd:ota_*` line. No new device-side dataclasses needed — bridge dispatches on `Ack.ack` name in `ota.py`.
- [ ] Add `Info` parser: when bridge receives `Ack(ack="info", ...)`, expose `data.version` / `data.board` / `data.features` to callers. Gate `claude-buddy update` on `"ota_v1" in features` — refuse with a clear error otherwise.
- [ ] Implement `bridge/src/claude_buddy_bridge/ota.py`:
  ```python
  async def push_firmware(client: BleClient, image: bytes, version: str,
                          progress_cb: Callable[[int, int], None] | None = None) -> None:
      """Push firmware bytes to a connected device. Raises OtaError on failure."""
  ```
  Algorithm:
  1. Compute SHA-256 of `image`.
  2. Send `cmd:ota_begin`, await `ack:ota_begin {ok:true}` (timeout 5 s; raise on `ok:false`).
  3. Chunk image into MTU-sized base64 payloads (~120 binary bytes per chunk at MTU 185).
  4. For each chunk: send `cmd:ota_data`. Every 32 chunks, await `ack:ota_data {ok:true, n:seq}` with matching `n` (timeout 2 s; abort + raise on miss).
  5. Send `cmd:ota_commit`. Await `ack:ota_commit {ok:true}` followed by disconnect (success — device rebooted) or `ack:ota_commit {ok:false, error:...}` (failure → raise).
- [ ] Add `bridge/tests/test_ota.py` with a fake `BleClient` that records writes and replays scripted responses. Cover happy path, begin failure, mid-stream chunk error, SHA mismatch at commit, missing `ota_v1` feature.

---

## Step 6 — `claude-buddy update --file path/to/firmware.bin`

- [ ] Extend `bridge/src/claude_buddy_bridge/cli.py` with an `update` subparser.
- [ ] Args: `--file PATH` (required for now; `--version STR` defaults to filename), `--device NAME` (optional, picks first paired device if absent).
- [ ] Reuse the existing connect-to-paired-device helper in `daemon.py` / `ble.py`. Connect, call `push_firmware`, render progress with `tqdm` or a plain stderr line.
- [ ] Manual test on hardware: build a test firmware locally with `pio run -e m5stack-core2`, then `claude-buddy update --file .pio/build/m5stack-core2/firmware.bin --version test-build`. Confirm device shows progress, reboots, comes back with the new build (heartbeat reports `version: test-build`).
- [ ] **Decision point**: if this works end-to-end, the OTA mechanism is functionally done. Steps 7-9 are polish + automation.

---

## Step 7 — `screens/ota.cpp` progress UI

- [ ] Create `src/screens/ota.h`/`src/screens/ota.cpp` with `screen::ota::draw()`:
  - Full-screen black background
  - Centered "OTA Update" title (size lg ? 3 : 2)
  - Centered version string (size 1, dimmed)
  - Centered progress bar — width 80% of screen, height 12px, filled by `ota::received() / ota::total()`
  - Below: percentage as text + "received/total bytes" line
- [ ] Modify `src/main.cpp` loop: at the top of the draw section, `if (ota::state() != ota::State::Idle) { screen::ota::draw(); hal::display::push(); return; }`. Skips all other screen routing.
- [ ] Make sure button input is ignored during OTA except power-button (which should be respected to abort — calling `ota::handle_command` with a synthesized `cmd:ota_abort` then powering off).
- [ ] Build both envs.

---

## Step 8 — Auto-rollback safety

- [ ] In `src/main.cpp`'s `setup()`, after `M5.begin()` and after the LittleFS mount succeeds, add:
  ```cpp
  #include <esp_ota_ops.h>
  esp_ota_mark_app_valid_cancel_rollback_after(30000);
  ```
- [ ] Smoke-test the rollback path locally: temporarily inject `abort();` early in `setup()` of a test build, OTA-flash it, observe device crash → reboot → revert to previous slot. Document in commit body. Revert the abort before merging.

---

## Step 9 — `release.py` GitHub Releases poller

- [ ] Implement `bridge/src/claude_buddy_bridge/release.py`:
  - `async def latest_for_board(board: str) -> Release | None` — queries `https://api.github.com/repos/onetxpanda/claude-desktop-buddy/releases/tags/latest`, finds the asset matching `<board>-firmware.bin`, fetches the matching `<board>-manifest.json` for SHA + version. ETag-cached.
  - `async def download_firmware(release: Release) -> bytes` — fetches the binary, verifies SHA against the manifest.
- [ ] Add `bridge/tests/test_release.py` — mock `aiohttp` (or `bleak`-style fixture) to assert the right URLs are hit, ETag is honored, SHA verification fails loudly on mismatch.
- [ ] Extend `claude-buddy update` (no `--file`): if no file, fetch from latest release for the connected device's board.

---

## Step 10 — Daemon integration with `auto_update` config

- [ ] Add to bridge config (TOML or whatever the daemon already reads): `auto_update = "prompt"` (default), with values `"prompt" | "auto" | "off"`.
- [ ] In `daemon.py`'s main loop: every N minutes (configurable, default 30), call `release.latest_for_board(device.board)`. If newer than `device.version`:
  - `auto`: kick off `push_firmware` immediately, log start/end.
  - `prompt`: post a system notification (`pync` on macOS, `notify-send` on Linux) with "New buddy firmware (X) available — confirm to install". Confirm action: kick off `push_firmware`. Dismiss: skip until next poll.
  - `off`: log `[release] new version X available; auto_update=off` and continue.
- [ ] Add a CLI surface: `claude-buddy update` (manual) and `claude-buddy update --check` (poll once, exit).

---

## Step 11 — Document migration for existing-device users

- [ ] Update `README.md` (or wherever the install flow is documented) with the one-time migration:
  - Existing devices need an erase+flash because the partition table changed
  - The WebUSB installer at https://onetxpanda.github.io/claude-desktop-buddy/ already passes `new_install_prompt_erase: true`, so users who use it get the right behavior automatically
  - CLI users: `esptool.py erase_flash` followed by the normal upload flow
- [ ] Note that subsequent firmware updates after the one-time migration flow over BLE and preserve NVS/LittleFS/bonds.

---

## Verification at end

- [ ] `pio run -e m5stickc-plus -e m5stack-core2` — both build clean
- [ ] `cd bridge && pixi run pytest` — all green
- [ ] CI workflow passes (firmware build + bridge tests + screenshots all happy)
- [ ] **Backward-compat check**: bridge running an OLD `protocol.py` (pre-Phase-C) connecting to NEW firmware does NOT raise on the `ack:info`/`ack:ota_*` messages — they parse as generic `Ack` and get logged but don't crash. Test by `git stash`-ing protocol.py changes, reconnecting, watching the daemon log.
- [ ] **Backward-compat check (other direction)**: NEW bridge sending `cmd:ota_*` to OLD firmware doesn't break it — old firmware's xferCommand catch-all swallows the unknowns; device stays responsive on its existing cmds. Test by checking out hal-refactor's firmware, flashing, then trying `claude-buddy update` (should refuse via missing `ota_v1` feature, not crash anything).
- [ ] Manual end-to-end test: paired device + `claude-buddy update --file .pio/build/m5stack-core2/firmware.bin` → progress visible on device + CLI → reboot → new version reported in `ack:info`
- [ ] Manual rollback test: build with `abort()` injected early in setup, OTA-flash, confirm device reverts to previous slot after crash
- [ ] Greps confirm no remaining `no_ota.csv` references; `Update.h` is included only from `src/ota.cpp`
