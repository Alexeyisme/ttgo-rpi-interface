#ifndef DISPLAY_MANAGER_H
#define DISPLAY_MANAGER_H

#include <TFT_eSPI.h>
#include <ArduinoJson.h>
#include "config.h"
#include "mode_base.h"
#include "mode_stats.h"
#include "mode_spotify.h"
#include "mode_weather.h"
#include "mode_image.h"

// ─────────────────────────────────────────────────────────────────────────────
// DisplayManager — owns the TFT and mode registry.
// ─────────────────────────────────────────────────────────────────────────────
class DisplayManager {
public:
    DisplayManager() : _modeIdx(0), _connected(false) {
        // Register modes in order — index matches MODE_* constants in config.h
        _modes[0] = new ModeStats();
        _modes[1] = new ModeSpotify();
        _modes[2] = new ModeWeather();
        _modes[3] = new ModeImage();
        // To add a new mode: create mode_mymode.h, add here, bump NUM_MODES in config.h
    }

    ~DisplayManager() {
        for (int i = 0; i < NUM_MODES; i++) delete _modes[i];
    }

    void begin() {
        _tft.init();
        _tft.setRotation(TFT_ROTATION);
        pinMode(TFT_BL, OUTPUT);
        digitalWrite(TFT_BL, HIGH);
        _tft.fillScreen(COL_BG);

        // Boot splash
        _tft.setTextFont(4);
        _tft.setTextColor(COL_CYAN, COL_BG);
        _tft.setCursor(8, 80);
        _tft.print("Hermes");
        _tft.setTextFont(2);
        _tft.setTextColor(COL_LABEL, COL_BG);
        _tft.setCursor(8, 120);
        _tft.print("Connecting...");
        delay(800);

        _modes[_modeIdx]->onEnter(_tft);
    }

    // Called when a JSON packet arrives from the transport.
    void handleData(JsonObject obj) {
        const char* type = obj["type"] | "";

        // "ack" messages: show a brief overlay regardless of current mode.
        if (strcmp(type, "ack") == 0) {
            _showAck(obj["text"] | "OK");
            return;
        }

        // Remote mode switch: {"type":"set_mode","mode":3}
        if (strcmp(type, "set_mode") == 0) {
            int m = obj["mode"] | -1;
            if (m >= 0 && m < NUM_MODES) {
                _modeIdx = m;
                _tft.fillScreen(COL_BG);
                _modes[_modeIdx]->onEnter(_tft);
            }
            return;
        }

        // Route to the current mode if the type matches.
        if (strcmp(type, _modes[_modeIdx]->typeName()) == 0) {
            _modes[_modeIdx]->onData(obj, _tft);
        }
    }

    // Cycle to the next mode.
    void nextMode() {
        _modeIdx = (_modeIdx + 1) % NUM_MODES;
        _tft.fillScreen(COL_BG);
        _modes[_modeIdx]->onEnter(_tft);
    }

    // Call every loop() — reserved for future animations.
    void tick() {}

    int currentMode() const { return _modeIdx; }

    void setConnected(bool c) {
        if (c == _connected) return;
        _connected = c;
        _modes[_modeIdx]->onConnected(c, _tft);
    }

private:
    TFT_eSPI     _tft;
    IDisplayMode* _modes[NUM_MODES];
    int          _modeIdx;
    bool         _connected;

    void _showAck(const char* text) {
        // Brief green banner at the bottom of the screen.
        int y = SCREEN_H - 26;
        _tft.fillRect(0, y, SCREEN_W, 26, 0x0460);
        _tft.setTextFont(2);
        _tft.setTextColor(TFT_WHITE, 0x0460);
        // Truncate to fit
        char buf[22];
        strncpy(buf, text, 21);
        buf[21] = '\0';
        int tw = _tft.textWidth(buf);
        _tft.setCursor((SCREEN_W - tw) / 2, y + 6);
        _tft.print(buf);
    }
};

#endif // DISPLAY_MANAGER_H
