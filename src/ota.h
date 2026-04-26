#pragma once
#include <stddef.h>
#include <stdint.h>
#include <ArduinoJson.h>

// Device-side OTA state machine. Driven by cmd:ota_* JSON lines from the
// bridge over the existing NUS UART link; emits evt:ota_* responses via
// the same channel. See docs/superpowers/specs/2026-04-26-phase-c-ble-ota-design.md
// for the protocol shapes and recovery semantics.

namespace ota {

enum class State { Idle, Receiving, Committing, Error };

State       state();
size_t      received();
size_t      total();
const char* error_msg();

// Returns true if `doc` is a cmd:ota_* and was handled. Caller (in
// data.h _applyJson) should short-circuit before xferCommand() if true.
bool handle_command(JsonDocument& doc);

// Drain a pending evt:ota_* into `out`. Returns true if one was written.
// Caller (main.cpp loop) should call repeatedly each iteration until false.
bool poll_event(char* out, size_t cap);

// Called from main.cpp loop. Triggers the deferred ESP.restart() after
// the post-commit grace period elapses.
void tick();

}
