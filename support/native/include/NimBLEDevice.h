// Stub. ble_bridge.cpp is excluded from the native build via build_src_filter;
// this header exists only because data.h transitively includes ble_bridge.h
// and some screens pull in M5Unified→M5GFX which doesn't need NimBLE — but we
// keep the header here for any stragglers. The shim is intentionally empty.
#pragma once
