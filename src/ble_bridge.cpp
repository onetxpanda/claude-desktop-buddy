#include "ble_bridge.h"
#include <NimBLEDevice.h>
#include <Arduino.h>
#include <string.h>
#include <esp_random.h>

// Nordic UART Service UUIDs — every BLE serial example uses these, so
// existing tools (nRF Connect, bluefy, Web Bluetooth examples) can talk to
// us without custom UUIDs.
#define NUS_SERVICE_UUID "6e400001-b5a3-f393-e0a9-e50e24dcca9e"
#define NUS_RX_UUID      "6e400002-b5a3-f393-e0a9-e50e24dcca9e"
#define NUS_TX_UUID      "6e400003-b5a3-f393-e0a9-e50e24dcca9e"

// Incoming bytes are buffered in a simple ring for bleRead()/bleAvailable().
// Sized to hold a transcript snapshot JSON plus headroom; the GATT layer
// will flow-control if we fall behind.
static const size_t RX_CAP = 2048;
static uint8_t  rxBuf[RX_CAP];
static volatile size_t rxHead = 0;
static volatile size_t rxTail = 0;

static NimBLEServer*         server = nullptr;
static NimBLECharacteristic* txChar = nullptr;
static NimBLECharacteristic* rxChar = nullptr;
static volatile bool      connected = false;
static volatile bool      secure = false;
static volatile uint32_t  passkey = 0;
static volatile uint16_t  mtu = 23;

static void rxPush(const uint8_t* p, size_t n) {
  for (size_t i = 0; i < n; i++) {
    size_t next = (rxHead + 1) % RX_CAP;
    if (next == rxTail) return;  // full — drop (upstream should keep up)
    rxBuf[rxHead] = p[i];
    rxHead = next;
  }
}

class RxCallbacks : public NimBLECharacteristicCallbacks {
  void onWrite(NimBLECharacteristic* c, NimBLEConnInfo& /*info*/) override {
    const std::string& v = c->getValue();
    if (!v.empty()) rxPush((const uint8_t*)v.data(), v.size());
  }
};

// LE Secure Connections, passkey-entry: we are DisplayOnly, the central is
// KeyboardOnly. NimBLE generates a random 6-digit passkey and calls
// onPassKeyDisplay; main.cpp polls blePasskey() to render it.
class ServerCallbacks : public NimBLEServerCallbacks {
  void onConnect(NimBLEServer* /*s*/, NimBLEConnInfo& /*info*/) override {
    connected = true;
    Serial.println("[ble] connected");
  }
  void onDisconnect(NimBLEServer* /*s*/, NimBLEConnInfo& /*info*/, int /*reason*/) override {
    connected = false;
    secure = false;
    passkey = 0;
    mtu = 23;
    Serial.println("[ble] disconnected");
    // Restart advertising so the next client can find us.
    NimBLEDevice::startAdvertising();
  }
  void onMTUChange(uint16_t newMtu, NimBLEConnInfo& /*info*/) override {
    mtu = newMtu;
    Serial.printf("[ble] mtu=%u\n", mtu);
  }
  uint32_t onPassKeyDisplay() override {
    uint32_t pk = esp_random() % 1000000U;
    passkey = pk;
    Serial.printf("[ble] passkey %06lu\n", (unsigned long)pk);
    return pk;
  }
  void onAuthenticationComplete(NimBLEConnInfo& info) override {
    passkey = 0;
    secure = info.isEncrypted();
    Serial.printf("[ble] auth %s\n", secure ? "ok" : "FAIL");
    if (!secure && server) {
      server->disconnect(info.getConnHandle());
    }
  }
};

void bleInit(const char* deviceName) {
  NimBLEDevice::init(deviceName);
  // Request the biggest MTU we can get. macOS negotiates to 185 typically.
  NimBLEDevice::setMTU(517);

  // LE Secure Connections + MITM + bonding (matches former Bluedroid config:
  // ESP_LE_AUTH_REQ_SC_MITM_BOND).
  NimBLEDevice::setSecurityAuth(/*bonding=*/true, /*mitm=*/true, /*sc=*/true);
  NimBLEDevice::setSecurityIOCap(BLE_HS_IO_DISPLAY_ONLY);

  server = NimBLEDevice::createServer();
  server->setCallbacks(new ServerCallbacks());

  NimBLEService* svc = server->createService(NUS_SERVICE_UUID);

  txChar = svc->createCharacteristic(
    NUS_TX_UUID,
    NIMBLE_PROPERTY::NOTIFY |
    NIMBLE_PROPERTY::READ_ENC | NIMBLE_PROPERTY::READ_AUTHEN
  );

  rxChar = svc->createCharacteristic(
    NUS_RX_UUID,
    NIMBLE_PROPERTY::WRITE | NIMBLE_PROPERTY::WRITE_NR |
    NIMBLE_PROPERTY::WRITE_ENC | NIMBLE_PROPERTY::WRITE_AUTHEN
  );
  rxChar->setCallbacks(new RxCallbacks());

  svc->start();

  NimBLEAdvertising* adv = NimBLEDevice::getAdvertising();
  adv->addServiceUUID(NUS_SERVICE_UUID);
  adv->setName(deviceName);
  adv->start();
  Serial.printf("[ble] advertising as '%s'\n", deviceName);
}

bool bleConnected() { return connected; }
bool bleSecure()    { return secure; }
uint32_t blePasskey() { return passkey; }

void bleClearBonds() {
  int n = NimBLEDevice::getNumBonds();
  if (n <= 0) return;
  NimBLEDevice::deleteAllBonds();
  Serial.printf("[ble] cleared %d bond(s)\n", n);
}

size_t bleAvailable() {
  return (rxHead + RX_CAP - rxTail) % RX_CAP;
}

int bleRead() {
  if (rxHead == rxTail) return -1;
  int b = rxBuf[rxTail];
  rxTail = (rxTail + 1) % RX_CAP;
  return b;
}

size_t bleWrite(const uint8_t* data, size_t len) {
  if (!connected || !txChar) return 0;
  // ATT notify payload is limited to (MTU - 3). macOS negotiates 185, so
  // the 182-byte chunk works there; use the live mtu so a peer that caps
  // at the 23-byte default doesn't get truncated notifies.
  size_t chunk = mtu > 3 ? mtu - 3 : 20;
  if (chunk > 180) chunk = 180;
  size_t sent = 0;
  while (sent < len) {
    size_t n = len - sent;
    if (n > chunk) n = chunk;
    txChar->setValue(data + sent, n);
    txChar->notify();
    sent += n;
    // Small yield so the BLE stack flushes before the next chunk.
    delay(4);
  }
  return sent;
}
