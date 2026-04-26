# Phase C — BLE-driven OTA (design)

- **Date**: 2026-04-26
- **Phase**: C of A→B→C. First major capability addition past the HAL/display work.
- **Prerequisite**: Phase B complete (HAL, M5Unified, Core2 build target, layouts, color fidelity all landed). Bridge available as a submodule at `bridge/` (claude-buddy-bridge, Python + bleak, already speaks the NUS UART JSON-line protocol).
- **Scope**: Switch the firmware partition table from `no_ota` to a two-slot OTA layout. Add an OTA command set on the existing NUS UART link so the bridge can push a new `firmware.bin` to the device, the device writes it into the inactive slot via `Update.h`, marks it bootable, and reboots. Bridge gains a polling task that watches the GitHub Releases `latest` tag and offers (or auto-applies) updates.
- **Acceptance**: A user with `claude-buddy run` running and the device paired can flash a new firmware image without touching a USB cable. NVS, BLE bonds, and LittleFS contents survive the update. A panic in the new image rolls back to the previous slot on the next boot.
- **Out of scope**: image signing / verified boot (NVS-stored peer key only — pairing already gates writes via MITM); OTA over Wi-Fi (no Wi-Fi stack linked); rollback UI; per-board fork of the OTA flow (StickC and Core2 share one path); delta updates.

## Why

CLAUDE.md's "Likely future direction" doesn't list OTA, but in practice every firmware change today requires a USB cable and `pio run -t upload`. That's fine for the developer working on the device but bad for a user who just owns one. With the build/release pipeline now publishing `firmware.bin` to a `latest` GitHub Release on every push, the device has a well-defined remote source for new images. The NUS link is already authenticated and encrypted (LE Secure Connections + MITM), the bridge already knows how to send line-delimited JSON, and `arduino-esp32`'s `Update.h` already handles the partition mechanics. The remaining work is just glue: a few command lines in the protocol, a state machine in the firmware, a small upload routine in the bridge.

The trade-off is half the app-slot space (each OTA slot ≈ 1.25 MB vs. the current ~1.94 MB single factory slot) and a one-time full-erase flash on every existing device to lay down the new partition table. CLAUDE.md says NVS at `0x9000–0xdfff` is preserved across upload-only flashes; with a partition table change that guarantee disappears for the migration flash, but standard OTA flashes after that preserve it again (NVS lives at the same offset in both layouts).

## Architecture

### Partition table

Replace `no_ota.csv` with `partitions_ota.csv`. New layout (4 MB flash, ESP32 classic):

```
# Name,    Type, SubType, Offset,   Size
nvs,       data, nvs,     0x9000,   0x5000     # 20 KB
otadata,   data, ota,     0xe000,   0x2000     # 8 KB    — tracks active slot
app0,      app,  ota_0,   0x10000,  0x140000   # 1.25 MB — slot A
app1,      app,  ota_1,   0x150000, 0x140000   # 1.25 MB — slot B
spiffs,    data, spiffs,  0x290000, 0x170000   # ~1.4 MB — LittleFS
```

Trade-offs (already discussed in chat — preserved here as the design baseline):

- `nvs` shrinks 24 KB → 20 KB. Fine: existing settings + bond LTKs use ~3 KB.
- `app` slot shrinks 1.94 MB → 1.25 MB each. Need to verify current firmware fits — `pio run -e m5stack-core2` reports ~1.0 MB today, so we have ~250 KB of headroom per slot.
- `spiffs` (LittleFS) shrinks 2 MB → 1.4 MB. Still room for 7-15 character GIFs at typical 50-200 KB each. CLAUDE.md notes the firmware autoformat-on-fail in `character.cpp`, so existing devices come up clean after the migration flash without a manual format step.
- `otadata` is the 8 KB region the bootloader reads to decide which slot to boot from.

`platformio.ini` changes per env: `board_build.partitions = partitions_ota.csv` (was `no_ota.csv`). The CSV file gets committed at the repo root.

Both StickC Plus (also 4 MB) and Core2 (16 MB) use the same 4 MB layout — Core2's extra 12 MB stays unused for now, but the layout could grow if we ever want larger app slots or a bigger filesystem on Core2 specifically.

### Existing protocol vocabulary (avoid collisions, don't repurpose)

Just so additions don't accidentally shadow existing names:

- **bridge → device `cmd:`** — `name`, `species`, `unpair`, `owner`, `status`, `char_begin`, `file`, `chunk`, `file_end`, `char_end`. All dispatched by `xferCommand()` in `xfer.h`.
- **bridge → device `evt:`** — `turn` only.
- **device → bridge `cmd:`** — `permission` only.
- **device → bridge `ack:NAME`** with `ok:bool, n:int?, error:str?, data:dict?` — used by `xfer.h` for file-transfer acknowledgments.

OTA picks fresh names that don't collide with any of those. Device-side dispatch needs to handle `cmd:ota_*` BEFORE `xferCommand()` is called, so xfer's catch-all doesn't silently consume them.

### BLE protocol additions

OTA layers on top of the existing NUS UART link — no new GATT services.

**bridge → device:**

```json
{"cmd":"ota_begin","size":1048576,"sha256":"e3b0c44...","version":"hal-refactor@a1b2c3d"}
{"cmd":"ota_data","seq":0,"b64":"<base64>"}
{"cmd":"ota_commit"}
{"cmd":"ota_abort"}
```

- `ota_begin` carries total firmware size, expected SHA-256, and a free-form version string. Device responds with `evt:ota_ready` if `Update.begin(size)` succeeded, `evt:ota_error` otherwise.
- `ota_data` carries one chunk. `seq` is monotonic from 0; `b64` is the base64-encoded chunk. Size chunks to the negotiated MTU minus JSON+base64 overhead — at the typical macOS MTU of 185, ~120 bytes of binary payload per chunk. ~9000 chunks for a 1.1 MB image, ~6 ms per chunk = ~55 s end-to-end. Device acks every Nth chunk (configurable; default 32).
- `ota_commit` triggers SHA verify, `Update.end(true)`, `esp_ota_set_boot_partition`, then a 200 ms grace period before `ESP.restart()` so the final notify drains.
- `ota_abort` calls `Update.abort()` and returns the device to idle. Useful if the bridge process dies mid-upload and reconnects; the user can also abort from the device's power button.

**device → bridge:**

```json
{"evt":"ota_ready"}
{"evt":"ota_ack","seq":127}                             // seq = highest committed to flash
{"evt":"ota_progress","pct":42}                         // for the bridge UI; device also draws on screen
{"evt":"ota_committed"}                                 // sent right before reboot; bridge expects disconnect
{"evt":"ota_error","msg":"sha mismatch at chunk 8642"}
```

`ota_progress` doubles as a keepalive — if the bridge sends data without seeing progress for ~3 s it should pause and re-sync.

We deliberately keep base64 in JSON rather than introducing a binary OTA characteristic. That trades ~33% throughput for sticking with a single transport and the existing NimBLE characteristic config (encryption-required, MITM-paired). At ~55 s for a full image, the throughput is acceptable; the user is sitting in front of the device watching a progress bar.

### Bridge parser relaxation

The bridge's current `decode_device_line` (`bridge/src/claude_buddy_bridge/protocol.py:147`) raises `ProtocolError` on any unrecognized device-side message — including new `evt:` shapes. Relax it to log + skip unknown shapes instead, so adding new device → bridge messages stops being a coordinated protocol-version bump. Old bridge code with new firmware emits some debug log lines but keeps working.

Single behavioral change in `decode_device_line`: replace the final `raise ProtocolError(f"unrecognized device message: {obj}")` with a log + return-None, and update callers to handle None as "skip this line." Add a regression test that asserts an unknown-evt line doesn't raise.

### Device-side state machine

New file `src/ota.cpp` + `src/ota.h`. State variables: `OtaState state`, `size_t total`, `size_t received`, `uint32_t expected_seq`, `uint8_t expected_sha[32]`, `uint8_t running_sha[32]`, `char version[32]`. States: `IDLE → RECEIVING → COMMITTING → REBOOT`, plus `ERROR`.

`ble_bridge.cpp`'s `_applyJson` (currently routes `cmd:permission` and `cmd:setOwner` etc.) gains a switch arm for `cmd:ota_*` that delegates to `ota::handle_command(JsonDocument&)`.

The device side uses `Update.h` (in-tree with arduino-esp32):

```cpp
#include <Update.h>
// in ota_begin:
Update.begin(total, U_FLASH);   // U_FLASH = app partition, not filesystem
// per chunk:
Update.write(buf, len);
// in ota_commit:
Update.end(true);               // true = set boot partition on success
ESP.restart();
```

`Update` writes directly to the inactive OTA slot (auto-detected via `esp_ota_get_next_update_partition`). On `Update.end(true)` it calls `esp_ota_set_boot_partition` so the next reboot lands in the new slot. If anything goes wrong before commit (chunk overflow, SHA mismatch, write error), we call `Update.abort()` and the device stays on the current slot.

**Rollback**: ESP-IDF supports app-version rollback via `esp_ota_mark_app_invalid_rollback_and_reboot`, but only if the new app explicitly marks itself valid via `esp_ota_mark_app_valid_cancel_rollback_after`. We add a one-line call in `setup()`:

```cpp
#include <esp_ota_ops.h>
esp_ota_mark_app_valid_cancel_rollback_after(/*ms=*/30000);
```

Meaning: the new firmware has 30 s to call this (which it does immediately after `M5.begin()` succeeds). If the new image panics or hangs before it gets to `setup()`, the bootloader's auto-rollback flips otadata back to the previous slot on the next watchdog reboot. No human intervention needed for "I bricked it with bad code" cases.

### Device-side UI during OTA

Add a new `screens/ota.cpp` that renders a full-screen progress bar with version string and chunk count. While `ota::state != IDLE`:

- main.cpp's loop short-circuits past the normal screen routing and calls `screen::ota::draw()` instead.
- HUD/menu/info inputs are ignored (otherwise A-tap could navigate away from the only visual feedback).
- Power-button stays live (user can abort by powering off — partition won't be committed, no harm).

The progress UI is its own commit; the OTA mechanism works without it (bridge shows progress in the CLI), but having it on-device matters for trust ("yes, the new firmware really is being received").

### Bridge-side flow

Three new things in `bridge/src/claude_buddy_bridge/`:

1. `ota.py` — pure protocol layer. Takes a `BleClient` and a `bytes` firmware image, runs the begin/data/commit dance, surfaces progress via an `asyncio.Queue` for the daemon to render.

2. `release.py` — polls `https://api.github.com/repos/onetxpanda/claude-desktop-buddy/releases/tags/latest` (HEAD request to check ETag, GET if changed). Caches the manifest's SHA256 + version. Triggers an OTA when device version (from heartbeat) differs from release version AND the user has opted in.

3. CLI surface in `cli.py`:
   - `claude-buddy update` — one-shot manual update from the latest release.
   - `claude-buddy update --file path/to/firmware.bin --version dev-build` — push a local binary (for development).
   - Daemon config `auto_update: prompt|auto|off` — **default `prompt`**, which posts a system notification and waits for confirmation. `off` is the developer-friendly setting (no surprise reboots while iterating); `auto` is for unattended deployments.

The download fetches the **board-specific** asset from the release: `m5stickc-plus-firmware.bin` or `m5stack-core2-firmware.bin`. The device tells the bridge which board it is via the existing `info` heartbeat field (we already have `btName` and MAC; add `board: "m5stickc-plus" | "m5stack-core2"` derived at build time from `ARDUINO_M5STACK_Core2` etc.). The bridge picks the matching asset; mismatched assets fail at the SHA check before any flash happens.

### Version reporting

Currently the firmware doesn't know its own version. Add at build time via PlatformIO's `extra_scripts` or just a plain `-D` flag set by the CI workflow:

```yaml
# In screenshots.yml's "Build firmware" step
build_flags:
  -DBUILD_VERSION=\"${branch}@${sha}\"
```

(Or a simpler `version.h` file generated by a pre-build script.) Firmware exposes via:

```cpp
extern const char* BUILD_VERSION;  // baked at build, format: "branch@sha7"
```

Sent once on bleConnected:

```json
{"evt":"info","board":"m5stack-core2","version":"hal-refactor@a1b2c3d","features":["ota_v1","xfer_v1"]}
```

Bridge reads `version` to decide whether an OTA is needed and `features` to gate which commands are safe to send (`ota_v1` present → `cmd:ota_*` is supported). Without the gate the bridge would silently no-op on old firmware and the user would have no idea why "update" did nothing.

## Files touched

**New:**
- `partitions_ota.csv` — partition table
- `src/ota.cpp` / `src/ota.h` — device OTA state machine
- `src/screens/ota.cpp` / `src/screens/ota.h` — progress screen
- `bridge/src/claude_buddy_bridge/ota.py` — protocol layer
- `bridge/src/claude_buddy_bridge/release.py` — GitHub Releases poller
- `docs/superpowers/plans/2026-04-26-phase-c-ble-ota.md` — implementation plan (next deliverable after this design)

**Modified:**
- `platformio.ini` — `board_build.partitions = partitions_ota.csv` in both ESP32 envs; `-DBUILD_VERSION=...` build flag
- `src/main.cpp` — `setup()` adds `esp_ota_mark_app_valid_cancel_rollback_after(30000);` and an info-event send; `loop()` routes to `screen::ota::draw()` when `ota::state != IDLE`
- `src/ble_bridge.cpp` — `_applyJson` switch arm for `cmd:ota_*`
- `src/data.h` — extend the protocol contract with the OTA shapes (so the JSON parsing stays in one place)
- `bridge/src/claude_buddy_bridge/protocol.py` — add OTA dataclasses to mirror the device shapes
- `bridge/src/claude_buddy_bridge/cli.py` — `update` subcommand
- `bridge/src/claude_buddy_bridge/daemon.py` — wire the release poller into the main loop
- `.github/workflows/screenshots.yml` — pass `-DBUILD_VERSION="${branch}@${sha}"` into the firmware build

**Migration cost (one-time per existing device):** `pio run -e <env> -t uploadfs` won't work — the partition layout changes, so the first install of this firmware needs `esptool.py erase_flash` followed by a normal upload (or the ESP Web Tools installer, which already passes `"new_install_prompt_erase": true`). After that one flash, all subsequent firmware changes flow through OTA and preserve NVS / LittleFS / BLE bonds.

## Risks worth calling out

- **App-slot fit at 1.25 MB.** Need to actually run `pio run -e m5stack-core2 -v | grep -E "Flash|RAM"` after flipping the partition table and confirm. If the app overflows, the recovery order is:
  1. **Shrink LittleFS first** (1.4 MB → 0.9 MB or whatever's needed) — gives both app slots more room without touching code. Character GIFs are the only LittleFS consumer; 0.9 MB still holds 4-9 typical (50-200 KB) GIFs.
  2. Drop unused M5GFX font subsets via `-DLGFX_USE_FONT_*=0` flags only as a fallback — Montserrat + Japanese + Korean + Chinese eat ~150 KB combined, but losing them would hurt future internationalization.
- **BLE throughput regressions.** The macOS MTU of 185 is best-case. If the negotiated MTU drops to 23 (default), chunks become tiny and a 1 MB image takes 5+ minutes. Mitigation: device sends `ota_error` with `code:"slow"` if MTU < 100 at `ota_begin`, bridge falls back to USB instructions.
- **Power loss mid-update.** `Update.h` writes are not atomic per chunk, but they ARE crash-safe per slot — the otadata partition only flips after `Update.end(true)`. Power loss before commit = boot to existing slot, no harm. Power loss after commit but before reboot also boots to new slot (already committed). The only ugly case is power loss DURING the `esp_ota_set_boot_partition` write itself, which is a few-ms window; CLAUDE.md doesn't say anything about RTC backup, so this is a "very rare, manual recovery via USB" scenario.
- **Bridge ↔ device version skew.** Two safety nets: (a) old device receiving `cmd:ota_*` from a new bridge silently swallows it via `xferCommand`'s catch-all — no crash, but no flash either. (b) New bridge gates `cmd:ota_*` on `"ota_v1" in features` from the device's `evt:info` — refuses with a clear error if the firmware doesn't advertise OTA support. The bridge parser relaxation (above) protects the other direction: old bridge + new firmware emitting `evt:ota_*` doesn't crash the bridge.
- **Image signing.** Out of scope for this phase. The pairing already authenticates the bridge as a trusted peer via MITM, and the SHA in `ota_begin` rules out transport corruption. A motivated attacker who's already paired could push a malicious image — but they could also just flash via USB if they have physical access, so pairing-as-authentication is the right level for a hobby device. Worth revisiting if/when the device gains Wi-Fi.

## Why a submodule for the bridge

The OTA work lives in two repos by necessity (Python on host, C++ on device). The submodule lets one PR / one CI workflow / one branch change both ends in lock-step during the protocol-design phase, while preserving independent release cycles afterward (the bridge ships to PyPI, the firmware ships to GitHub Releases). The submodule pin is just a commit reference — bumping it is a one-line PR.

CI grows a parallel `bridge` job that runs `pixi install && pixi run pytest` against the submodule's pinned commit on every push. That keeps the protocol contract honest — if the device side adds a new `cmd` or `evt` shape and the bridge's `protocol.py` doesn't match, the bridge tests catch it before either ships. The job uses `actions/checkout@v4` with `submodules: recursive`.

If at any point the bridge feels like its own project again, `git submodule deinit` cleanly detaches it and the standalone repo carries on. Low cost in either direction.

## Next deliverable

`docs/superpowers/plans/2026-04-26-phase-c-ble-ota.md` — step-by-step implementation order, written after this design is reviewed. Rough sketch:

1. Add `partitions_ota.csv`, build, verify size fit on both boards.
2. Wire up `BUILD_VERSION` and the `info` event end-to-end.
3. Device-side `ota.cpp` minimal happy path (no UI, no rollback).
4. Bridge-side `ota.py` + `claude-buddy update --file`.
5. Test the full loop with a hand-built `firmware.bin` over BLE.
6. Add `screens/ota.cpp` progress UI.
7. Add rollback (`mark_app_valid_cancel_rollback_after`) + crash-test by injecting a panic in setup of a test build.
8. Add `release.py` GitHub poller + `claude-buddy update` (no `--file`).
9. Daemon integration with `auto_update` config.
10. Document migration path for existing-device users (one-time erase+flash via the WebUSB installer).
