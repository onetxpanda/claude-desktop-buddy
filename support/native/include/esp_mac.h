#pragma once
#include <stdint.h>
#include <string.h>

enum { ESP_MAC_BT = 1, ESP_MAC_WIFI_STA = 2 };

inline int esp_read_mac(uint8_t* mac, int) {
  // Stable fake MAC so the emulator advertises as a consistent name.
  static const uint8_t fake[6] = { 0x02, 0x00, 0xC1, 0xAA, 0xDE, 0x42 };
  if (mac) memcpy(mac, fake, 6);
  return 0;
}
