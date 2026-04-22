// firmware/ws_transport.h
// WiFi + WebSocket transport — replaces serial_protocol.h for wireless mode.
//
// Connects ESP32 to home WiFi and maintains a WebSocket client connection
// to the RPi bridge server. Provides same API as SerialProtocol:
//   begin()          — init WiFi + WS
//   poll()           — process incoming WS frames, returns true if JSON ready
//   getDoc()         — access last parsed JsonDocument
//   sendEvent()      — send {"event":"..."} to RPi
//   sendModeChange() — send {"event":"mode_changed","mode":N} to RPi
//
// Reconnect behavior:
//   WiFi: auto-managed by ESP32 SDK (reconnects on drop).
//   WS:   reconnect loop in poll() — retries every WS_RECONNECT_MS if disconnected.

#ifndef WS_TRANSPORT_H
#define WS_TRANSPORT_H

#include <Arduino.h>
#include <WiFi.h>
#include <WebSocketsClient.h>
#include <ArduinoJson.h>
#include "wifi_config.h"

#define WS_RECONNECT_MS   3000   // ms between WS reconnect attempts
#define WS_JSON_DOC_SIZE  40000  // same as serial_protocol.h SERIAL_JSON_DOC_SIZE

class WsTransport {
public:
    WsTransport() : _ready(false), _msgReady(false), _lastReconnectMs(0) {}

    void begin() {
        // Connect WiFi
        WiFi.mode(WIFI_STA);
        WiFi.begin(WIFI_SSID, WIFI_PASSWORD);

        // Block until WiFi connects (with timeout)
        unsigned long t = millis();
        while (WiFi.status() != WL_CONNECTED && millis() - t < 15000) {
            delay(200);
        }

        // Setup WS client
        _ws.begin(WS_HOST, WS_PORT, WS_PATH);
        _ws.onEvent([this](WStype_t type, uint8_t* payload, size_t length) {
            this->_onWsEvent(type, payload, length);
        });
        _ws.setReconnectInterval(WS_RECONNECT_MS);
        _ws.enableHeartbeat(15000, 3000, 2);  // ping every 15s, pong timeout 3s, 2 retries
    }

    // Call in loop(). Returns true if a complete JSON message arrived.
    bool poll() {
        _ws.loop();
        if (_msgReady) {
            _msgReady = false;
            return true;
        }
        return false;
    }

    bool connected() const {
        return _ready && WiFi.status() == WL_CONNECTED;
    }

    JsonDocument& getDoc() { return _doc; }

    void sendEvent(const char* eventName) {
        if (!_ready) return;
        char buf[64];
        snprintf(buf, sizeof(buf), "{\"event\":\"%s\"}", eventName);
        _ws.sendTXT(buf);
    }

    void sendModeChange(int modeIndex) {
        if (!_ready) return;
        char buf[48];
        snprintf(buf, sizeof(buf), "{\"event\":\"mode_changed\",\"mode\":%d}", modeIndex);
        _ws.sendTXT(buf);
    }

    void sendRaw(const char* json) {
        if (!_ready) return;
        _ws.sendTXT(json);
    }

    String ipAddress() const {
        return WiFi.localIP().toString();
    }

private:
    WebSocketsClient _ws;
    StaticJsonDocument<WS_JSON_DOC_SIZE> _doc;
    bool   _ready;
    bool   _msgReady;
    unsigned long _lastReconnectMs;

    void _onWsEvent(WStype_t type, uint8_t* payload, size_t length) {
        switch (type) {
            case WStype_CONNECTED:
                _ready = true;
                break;

            case WStype_DISCONNECTED:
                _ready = false;
                break;

            case WStype_TEXT: {
                DeserializationError err = deserializeJson(_doc, payload, length);
                if (!err) {
                    _msgReady = true;
                }
                break;
            }

            default:
                break;
        }
    }
};

#endif // WS_TRANSPORT_H
