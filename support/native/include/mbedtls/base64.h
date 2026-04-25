// Stub mbedtls base64 for native build. Never actually invoked at runtime —
// BLE is stubbed so xfer file-transfer state never advances — but xfer.h
// includes this header unconditionally so the symbol must exist to compile.
#pragma once
#include <stddef.h>

static inline int mbedtls_base64_decode(unsigned char* dst, size_t dlen, size_t* olen,
                                        const unsigned char* /*src*/, size_t /*slen*/) {
  (void)dst; (void)dlen;
  if (olen) *olen = 0;
  return -1;
}
