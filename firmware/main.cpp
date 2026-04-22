#include <Arduino.h>
#include "config.h"
#include "ws_transport.h"
#include "display_manager.h"

// ─────────────────────────────────────────────────────────────────────────────
// Globals
// ─────────────────────────────────────────────────────────────────────────────
WsTransport  proto;
DisplayManager  display;

// Button state (ISR-safe via volatile)
volatile bool btn1Pressed  = false;
volatile bool btn2Down     = false;
volatile bool btn2Released = false;

unsigned long btn1LastMs  = 0;
unsigned long btn2PressMs = 0;
bool          btn2WasPtt  = false;   // Did this hold trigger PTT?

// Connection watchdog
unsigned long lastDataMs = 0;
bool          wasConnected = false;

// ─────────────────────────────────────────────────────────────────────────────
// Button ISRs
// ─────────────────────────────────────────────────────────────────────────────
void IRAM_ATTR onBtn1() {
    unsigned long now = millis();
    if (now - btn1LastMs > BTN_DEBOUNCE_MS) {
        btn1Pressed = true;
        btn1LastMs  = now;
    }
}

void IRAM_ATTR onBtn2Down() {
    // GPIO 0 is active LOW; falling edge = press
    btn2Down = true;
}

void IRAM_ATTR onBtn2Up() {
    btn2Released = true;
}

// ─────────────────────────────────────────────────────────────────────────────
void setup() {
    proto.begin();

    Serial.begin(115200);  // Debug output only (not data transport)
    Serial.printf("WiFi IP: %s\n", proto.ipAddress().c_str());

    // Button pins
    pinMode(BTN1_PIN, INPUT);          // GPIO35 — input only, no internal pull-up
    pinMode(BTN2_PIN, INPUT_PULLUP);   // GPIO0  — has internal pull-up

    attachInterrupt(digitalPinToInterrupt(BTN1_PIN), onBtn1,    FALLING);
    attachInterrupt(digitalPinToInterrupt(BTN2_PIN), onBtn2Down, FALLING);
    attachInterrupt(digitalPinToInterrupt(BTN2_PIN), onBtn2Up,   RISING);

    display.begin();

    // Send a hello so the RPi bridge knows we're ready.
    proto.sendEvent("device_ready");
}

// ─────────────────────────────────────────────────────────────────────────────
void loop() {
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

    // ── Button 1 — cycle mode ─────────────────────────────────────────────────
    if (btn1Pressed) {
        btn1Pressed = false;
        display.nextMode();
        proto.sendModeChange(display.currentMode());
    }

    // ── Button 2 — PTT ────────────────────────────────────────────────────────
    if (btn2Down) {
        btn2Down    = false;
        btn2PressMs = millis();
        btn2WasPtt  = false;
    }

    // Activate PTT after hold threshold
    if (!btn2WasPtt && btn2PressMs > 0 && !digitalRead(BTN2_PIN)) {
        if (millis() - btn2PressMs >= BTN2_HOLD_MS) {
            btn2WasPtt = true;
            display.pttStart();
            proto.sendEvent("ptt_start");
        }
    }

    if (btn2Released) {
        btn2Released = false;
        if (btn2WasPtt) {
            display.pttStop();
            proto.sendEvent("ptt_stop");
        }
        btn2PressMs = 0;
        btn2WasPtt  = false;
    }

    // ── Animation ticks ───────────────────────────────────────────────────────
    display.tick();
}
