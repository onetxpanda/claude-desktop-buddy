#include "ota.h"

#include <Arduino.h>
#include <ArduinoJson.h>
#include <Update.h>
#include <mbedtls/base64.h>
#include <mbedtls/md.h>
#include <string.h>

namespace ota {

static State    _state = State::Idle;
static size_t   _total = 0;
static size_t   _received = 0;
static uint32_t _expected_seq = 0;
static char     _error[64] = "";
// SHA expected from the bridge; lowercase hex, 64 chars + null.
static char     _expected_sha_hex[65] = "";
static char     _version[32] = "";

static mbedtls_md_context_t _md_ctx;
static bool _md_init = false;

static uint32_t _commit_at_ms = 0;

// Single-slot pending-event buffer. Most commands produce at most one
// event; if we ever overrun, the dropped event isn't fatal — bridge
// times out, retransmits, or aborts.
static bool _has_pending = false;
static char _pending[160] = "";

State       state()        { return _state; }
size_t      received()     { return _received; }
size_t      total()        { return _total; }
const char* error_msg()    { return _error; }

static void _enqueue(const char* json) {
  if (_has_pending) return;  // drop — see comment above
  strncpy(_pending, json, sizeof(_pending) - 1);
  _pending[sizeof(_pending) - 1] = 0;
  _has_pending = true;
}

static void _hex_from_bytes(const uint8_t* in, size_t n, char* out) {
  static const char k[] = "0123456789abcdef";
  for (size_t i = 0; i < n; i++) {
    out[i * 2]     = k[(in[i] >> 4) & 0xf];
    out[i * 2 + 1] = k[in[i] & 0xf];
  }
  out[n * 2] = 0;
}

static void _to_error(const char* msg) {
  strncpy(_error, msg, sizeof(_error) - 1);
  _error[sizeof(_error) - 1] = 0;
  if (_md_init) { mbedtls_md_free(&_md_ctx); _md_init = false; }
  Update.abort();
  _state = State::Error;

  char buf[128];
  snprintf(buf, sizeof(buf), "{\"evt\":\"ota_error\",\"msg\":\"%s\"}", _error);
  _enqueue(buf);
}

static bool _begin_sha() {
  if (_md_init) mbedtls_md_free(&_md_ctx);
  mbedtls_md_init(&_md_ctx);
  if (mbedtls_md_setup(&_md_ctx, mbedtls_md_info_from_type(MBEDTLS_MD_SHA256), 0) != 0) {
    return false;
  }
  if (mbedtls_md_starts(&_md_ctx) != 0) return false;
  _md_init = true;
  return true;
}

bool handle_command(JsonDocument& doc) {
  const char* cmd = doc["cmd"];
  if (!cmd || strncmp(cmd, "ota_", 4) != 0) return false;

  // ── ota_begin ──────────────────────────────────────────────────────
  if (strcmp(cmd, "ota_begin") == 0) {
    // If we're mid-anything, reset cleanly first.
    if (_state == State::Receiving || _state == State::Committing) {
      Update.abort();
    }
    if (_md_init) { mbedtls_md_free(&_md_ctx); _md_init = false; }
    _state = State::Idle;
    _has_pending = false;

    size_t size = doc["size"] | (size_t)0;
    const char* sha = doc["sha256"] | "";
    const char* ver = doc["version"] | "";
    if (size == 0 || strlen(sha) != 64) {
      _to_error("malformed ota_begin");
      return true;
    }
    if (!Update.begin(size, U_FLASH)) {
      char err[64];
      snprintf(err, sizeof(err), "begin: %s", Update.errorString());
      _to_error(err);
      return true;
    }
    if (!_begin_sha()) {
      Update.abort();
      _to_error("sha init");
      return true;
    }
    _total = size;
    _received = 0;
    _expected_seq = 0;
    strncpy(_expected_sha_hex, sha, 64);
    _expected_sha_hex[64] = 0;
    strncpy(_version, ver, sizeof(_version) - 1);
    _version[sizeof(_version) - 1] = 0;
    _state = State::Receiving;
    _enqueue("{\"evt\":\"ota_ready\"}");
    return true;
  }

  // ── ota_data ───────────────────────────────────────────────────────
  if (strcmp(cmd, "ota_data") == 0) {
    if (_state != State::Receiving) {
      _to_error("data outside receiving state");
      return true;
    }
    uint32_t seq = doc["seq"] | (uint32_t)0xFFFFFFFFu;
    const char* b64 = doc["b64"] | "";
    if (seq != _expected_seq) {
      char err[64];
      snprintf(err, sizeof(err), "seq mismatch (got %lu want %lu)",
               (unsigned long)seq, (unsigned long)_expected_seq);
      _to_error(err);
      return true;
    }
    size_t b64len = strlen(b64);
    // Max base64 length per chunk: ~250 bytes (decodes to ~187). Buffer
    // at 256 leaves room for any MTU growth without overflowing.
    uint8_t buf[256];
    size_t out_len = 0;
    int rc = mbedtls_base64_decode(buf, sizeof(buf), &out_len,
                                   (const uint8_t*)b64, b64len);
    if (rc != 0) { _to_error("base64 decode"); return true; }
    if (Update.write(buf, out_len) != out_len) {
      char err[64];
      snprintf(err, sizeof(err), "write: %s", Update.errorString());
      _to_error(err);
      return true;
    }
    mbedtls_md_update(&_md_ctx, buf, out_len);
    _received += out_len;
    _expected_seq++;

    // Ack every 32 chunks (bounds bridge retransmit cost).
    if ((_expected_seq % 32) == 0) {
      char ack[64];
      snprintf(ack, sizeof(ack), "{\"evt\":\"ota_ack\",\"seq\":%lu}",
               (unsigned long)(_expected_seq - 1));
      _enqueue(ack);
    }
    // Progress every 64 chunks or on completion (~1% granularity).
    if ((_expected_seq % 64) == 0 || _received >= _total) {
      uint8_t pct = _total ? (uint8_t)((_received * 100ULL) / _total) : 0;
      if (pct > 100) pct = 100;
      char prog[64];
      snprintf(prog, sizeof(prog), "{\"evt\":\"ota_progress\",\"pct\":%u}", pct);
      _enqueue(prog);
    }
    return true;
  }

  // ── ota_commit ─────────────────────────────────────────────────────
  if (strcmp(cmd, "ota_commit") == 0) {
    if (_state != State::Receiving) {
      _to_error("commit outside receiving state");
      return true;
    }
    uint8_t got[32];
    mbedtls_md_finish(&_md_ctx, got);
    mbedtls_md_free(&_md_ctx);
    _md_init = false;

    char got_hex[65];
    _hex_from_bytes(got, 32, got_hex);
    if (strcmp(got_hex, _expected_sha_hex) != 0) {
      _to_error("sha mismatch");
      return true;
    }
    if (!Update.end(true)) {
      char err[64];
      snprintf(err, sizeof(err), "end: %s", Update.errorString());
      _to_error(err);
      return true;
    }
    _enqueue("{\"evt\":\"ota_committed\"}");
    _state = State::Committing;
    // Grace period before reboot so the final notify drains over BLE.
    _commit_at_ms = millis() + 200;
    return true;
  }

  // ── ota_abort ──────────────────────────────────────────────────────
  if (strcmp(cmd, "ota_abort") == 0) {
    if (_md_init) { mbedtls_md_free(&_md_ctx); _md_init = false; }
    Update.abort();
    _state = State::Idle;
    _enqueue("{\"evt\":\"ota_aborted\"}");
    return true;
  }

  // Unknown ota_* — we still claim it as handled (don't fall through
  // to xferCommand which would also claim it via its catch-all).
  return true;
}

bool poll_event(char* out, size_t cap) {
  if (!_has_pending || cap == 0) return false;
  strncpy(out, _pending, cap - 1);
  out[cap - 1] = 0;
  _has_pending = false;
  return true;
}

void tick() {
  if (_state == State::Committing &&
      (int32_t)(millis() - _commit_at_ms) >= 0) {
    ESP.restart();
  }
}

} // namespace ota
