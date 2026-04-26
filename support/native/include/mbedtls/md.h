// Native (SDL emulator) stub for mbedtls SHA-256. The real mbedtls is
// linked from arduino-esp32; on host we skip actual hashing — the
// "computed" hash is always zeros, which means the SHA verify step in
// src/ota.cpp will fail unless the bridge sends an all-zeros expected
// hash. Acceptable: we don't actually OTA on the emulator, this stub
// just lets ota.cpp compile.
#pragma once
#include <stddef.h>
#include <stdint.h>
#include <string.h>

typedef enum { MBEDTLS_MD_NONE = 0, MBEDTLS_MD_SHA256 = 6 } mbedtls_md_type_t;
typedef struct mbedtls_md_info_t { int unused; } mbedtls_md_info_t;
typedef struct mbedtls_md_context_t { int unused; } mbedtls_md_context_t;

inline const mbedtls_md_info_t* mbedtls_md_info_from_type(mbedtls_md_type_t) {
  static mbedtls_md_info_t info{};
  return &info;
}
inline void mbedtls_md_init(mbedtls_md_context_t*) {}
inline void mbedtls_md_free(mbedtls_md_context_t*) {}
inline int  mbedtls_md_setup(mbedtls_md_context_t*, const mbedtls_md_info_t*, int) { return 0; }
inline int  mbedtls_md_starts(mbedtls_md_context_t*) { return 0; }
inline int  mbedtls_md_update(mbedtls_md_context_t*, const uint8_t*, size_t) { return 0; }
inline int  mbedtls_md_finish(mbedtls_md_context_t*, uint8_t* out) {
  if (out) memset(out, 0, 32);
  return 0;
}
