#include <Arduino.h>
#include <ArduinoOTA.h>
#include "config.h"
#include "ws_transport.h"
#include "display_manager.h"

// ─────────────────────────────────────────────────────────────────────────────
// Globals
// ─────────────────────────────────────────────────────────────────────────────
WsTransport  proto;
DisplayManager  display;

// Button state (ISR-safe via volatile)
// Mode cycling is now on GPIO0 (active LOW).
volatile bool modeBtnPressed = false;
unsigned long modeBtnLastMs  = 0;

// Connection watchdog
unsigned long lastDataMs = 0;
bool          wasConnected = false;

// ─────────────────────────────────────────────────────────────────────────────
// Button ISR
// ─────────────────────────────────────────────────────────────────────────────
void IRAM_ATTR onModeBtn() {
    unsigned long now = millis();
    if (now - modeBtnLastMs > BTN_DEBOUNCE_MS) {
        modeBtnPressed = true;
        modeBtnLastMs  = now;
    }
}

// ─────────────────────────────────────────────────────────────────────────────
void setup() {
    proto.begin();

    Serial.begin(115200);  // Debug output only (not data transport)
    Serial.printf("WiFi IP: %s\n", proto.ipAddress().c_str());

    // ── OTA (Over-the-Air) update setup ──────────────────────────────────────
    ArduinoOTA.setHostname(OTA_HOSTNAME);
    ArduinoOTA.setPassword(OTA_PASSWORD);
    ArduinoOTA.onStart([]() {
        Serial.println("OTA: start");
    });
    ArduinoOTA.onEnd([]() {
        Serial.println("OTA: done — rebooting");
    });
    ArduinoOTA.onError([](ota_error_t err) {
        Serial.printf("OTA error [%u]\n", err);
    });
    ArduinoOTA.begin();
    Serial.println("OTA ready");

    // Button pins
    // Top button (GPIO35) is physically broken.
    // Mode cycling on GPIO0 (active LOW, needs external pull-up).
    pinMode(MODE_BTN_PIN, INPUT_PULLUP);

    attachInterrupt(digitalPinToInterrupt(MODE_BTN_PIN), onModeBtn, FALLING);

    display.begin();

    // Send a hello so the RPi bridge knows we're ready.
    proto.sendEvent("device_ready");
}

// ─────────────────────────────────────────────────────────────────────────────
void loop() {
    // ── OTA handler — must be called every loop ───────────────────────────────
    ArduinoOTA.handle();

    // ── Serial protocol polling ───────────────────────────────────────────────
    if (proto.poll()) {
        lastDataMs = millis();
        display.setConnected(true);
        wasConnected = true;

        JsonDocument& doc = proto.getDoc();
        JsonObject obj = doc.as<JsonObject>();
        display.handleData(obj);
    }

    // ── Connection watchdog ───────────────────────────────────────────────────
    if (wasConnected && millis() - lastDataMs > STALE_DATA_MS) {
        display.setConnected(false);
    }

    // ── Mode button (GPIO32) — cycle mode ─────────────────────────────────────────
    if (modeBtnPressed) {
        modeBtnPressed = false;
        display.nextMode();
        proto.sendModeChange(display.currentMode());
    }

    // ── Animation ticks ───────────────────────────────────────────────────────
    display.tick();
}
