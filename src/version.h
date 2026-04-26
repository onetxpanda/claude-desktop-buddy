#pragma once

// BUILD_VERSION identifies which firmware build is running. Format is
// "<branch>@<short-sha>" (e.g. "hal-refactor@a1b2c3d") when injected by CI;
// falls back to "dev-local" for local builds without the define set.
//
// Sourced from -DCLAUDE_BUILD_VERSION="..." passed by .github/workflows/
// screenshots.yml. Embedded into the evt:info message the device emits
// once on every BLE connection so the bridge can decide whether an OTA
// is needed.
extern const char* const BUILD_VERSION;
