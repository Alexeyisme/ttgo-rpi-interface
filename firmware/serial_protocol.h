#ifndef SERIAL_PROTOCOL_H
#define SERIAL_PROTOCOL_H

#include <Arduino.h>
#include <ArduinoJson.h>

// ─────────────────────────────────────────────────────────────────────────────
// SerialProtocol — newline-delimited JSON framing over Serial.
//
// RPi → TTGO (incoming):
//   {"type":"stats",   "cpu":12.3, "ram":342, "temp":41.2, "disk":18.4}
//   {"type":"spotify", "track":"...", "artist":"...", "playing":true, "progress_pct":42}
//   {"type":"weather", "temp_out":22.1, "hum_out":55, "temp_in":24.0, "hum_in":48, "aqi":52}
//   {"type":"image",   "jpeg_b64":"<base64>"}
//   {"type":"ack",     "text":"Playing jazz..."}
//
// TTGO → RPi (outgoing):
//   {"event":"device_ready"}
//   {"event":"mode_changed","mode":N}
// ─────────────────────────────────────────────────────────────────────────────

#define SP_BUF_SIZE 32768   // 32 KB — more headroom for base64 image JSON line at higher baud

// ArduinoJson document capacity for incoming packets.
// Image packets can include a ~7-10KB base64 string; without enough
// capacity deserializeJson() will fail and the TTGO will never receive
// any `type:"image"` data.
#ifndef SERIAL_JSON_DOC_SIZE
#define SERIAL_JSON_DOC_SIZE 40000
#endif

class SerialProtocol {
public:
    SerialProtocol() : _bufPos(0) {}

    void begin() {
        Serial.begin(SERIAL_BAUD_RATE);
        _bufPos = 0;
    }

    // Call in loop(). Returns true if a complete JSON object was parsed.
    // Caller reads via getDoc().
    bool poll() {
        while (Serial.available()) {
            char c = (char)Serial.read();
            if (c == '\n') {
                _buf[_bufPos] = '\0';
                if (_bufPos > 0) {
                    _bufPos = 0;
                    DeserializationError err = deserializeJson(_doc, _buf);
                    if (!err) return true;
                }
                _bufPos = 0;
            } else {
                if (_bufPos < SP_BUF_SIZE - 1) {
                    _buf[_bufPos++] = c;
                } else {
                    // Buffer overflow — discard line
                    _bufPos = 0;
                }
            }
        }
        return false;
    }

    JsonDocument& getDoc() { return _doc; }

    // Send a button event to the RPi.
    void sendEvent(const char* eventName) {
        Serial.print("{\"event\":\"");
        Serial.print(eventName);
        Serial.print("\"}\n");
    }

    // Send a mode-change notification.
    void sendModeChange(int modeIndex) {
        Serial.print("{\"event\":\"mode_changed\",\"mode\":");
        Serial.print(modeIndex);
        Serial.print("}\n");
    }

private:
    char _buf[SP_BUF_SIZE];
    int  _bufPos;
    // Sized document to handle image packets.
    StaticJsonDocument<SERIAL_JSON_DOC_SIZE> _doc;
};

#endif // SERIAL_PROTOCOL_H
