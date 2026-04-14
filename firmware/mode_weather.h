#ifndef MODE_WEATHER_H
#define MODE_WEATHER_H

#include "mode_base.h"

// ─────────────────────────────────────────────────────────────────────────────
// ModeWeather — Home Assistant weather data.
//
// Layout:
//   [ Weather                ● ]
//   OUTDOOR
//     Temp   22.1°C
//     Hum    55%
//   ─────────────────────────────
//   INDOOR
//     Temp   24.0°C
//     Hum    48%
//     AQI    52 Good
// ─────────────────────────────────────────────────────────────────────────────
class ModeWeather : public IDisplayMode {
public:
    const char* typeName()    const override { return "weather"; }
    const char* displayName() const override { return "Weather"; }

    void onEnter(TFT_eSPI& tft) override {
        tft.fillScreen(COL_BG);
        drawHeader(tft, "Weather", _connected);
        _drawAll(tft);
    }

    void onData(JsonObject data, TFT_eSPI& tft) override {
        _tempOut = data["temp_out"] | -99.0f;
        _humOut  = data["hum_out"]  | -1.0f;
        _tempIn  = data["temp_in"]  | -99.0f;
        _humIn   = data["hum_in"]   | -1.0f;
        _aqi     = data["aqi"]      | -1;
        _staleAt = millis() + STALE_DATA_MS;
        _connected = true;
        drawHeader(tft, "Weather", _connected);
        _drawAll(tft);
    }

    void onConnected(bool connected, TFT_eSPI& tft) override {
        _connected = connected;
        drawHeader(tft, "Weather", _connected);
    }

private:
    float _tempOut = -99, _humOut = -1;
    float _tempIn  = -99, _humIn  = -1;
    int   _aqi = -1;
    bool  _connected = false;
    unsigned long _staleAt = 0;

    void _drawAll(TFT_eSPI& tft) {
        bool stale = (_staleAt > 0 && millis() > _staleAt);
        tft.fillRect(0, 24, SCREEN_W, SCREEN_H - 24, COL_BG);

        // OUTDOOR section header
        tft.setTextFont(2);
        tft.setTextColor(COL_ORANGE, COL_BG);
        tft.setCursor(4, 28);
        tft.print("OUTDOOR");

        _drawTempHum(tft, _tempOut, _humOut, 46, stale);

        // Divider
        tft.drawFastHLine(0, 100, SCREEN_W, COL_HEADER);

        // INDOOR section header
        tft.setTextColor(COL_CYAN, COL_BG);
        tft.setCursor(4, 106);
        tft.print("INDOOR");

        _drawTempHum(tft, _tempIn, _humIn, 124, stale);

        // AQI
        _drawAqi(tft, 162, stale);
    }

    void _drawTempHum(TFT_eSPI& tft, float temp, float hum, int y, bool stale) {
        uint16_t vc = stale ? COL_STALE : COL_VALUE;

        // Temp
        tft.setTextFont(2);
        tft.setTextColor(COL_LABEL, COL_BG);
        tft.setCursor(4, y);
        tft.print("Temp");

        tft.setTextFont(4);
        tft.setTextColor(vc, COL_BG);
        char buf[12];
        if (temp > -90.0f) {
            snprintf(buf, sizeof(buf), "%.1f", temp);
        } else {
            strcpy(buf, "---");
        }
        tft.setCursor(60, y - 2);
        tft.print(buf);
        tft.setTextFont(2);
        tft.setCursor(60 + tft.textWidth(buf, 4), y + 6);
        tft.print(" C");

        // Hum
        tft.setTextFont(2);
        tft.setTextColor(COL_LABEL, COL_BG);
        tft.setCursor(4, y + 26);
        tft.print("Hum");
        tft.setTextColor(vc, COL_BG);
        if (hum >= 0.0f) {
            snprintf(buf, sizeof(buf), "%.0f%%", hum);
        } else {
            strcpy(buf, "---%");
        }
        tft.setCursor(60, y + 26);
        tft.print(buf);
    }

    void _drawAqi(TFT_eSPI& tft, int y, bool stale) {
        tft.setTextFont(2);
        tft.setTextColor(COL_LABEL, COL_BG);
        tft.setCursor(4, y);
        tft.print("AQI");

        if (_aqi < 0) {
            tft.setTextColor(stale ? COL_STALE : COL_LABEL, COL_BG);
            tft.setCursor(60, y);
            tft.print("---");
            return;
        }

        // Color-coded AQI
        uint16_t ac;
        const char* label;
        if (_aqi <= 50)       { ac = COL_GREEN;  label = "Good"; }
        else if (_aqi <= 100) { ac = COL_YELLOW; label = "OK"; }
        else if (_aqi <= 150) { ac = COL_ORANGE; label = "Poor"; }
        else                  { ac = COL_RED;    label = "Bad"; }

        char buf[16];
        snprintf(buf, sizeof(buf), "%d %s", _aqi, label);
        tft.setTextColor(ac, COL_BG);
        tft.setCursor(60, y);
        tft.print(buf);
    }
};

#endif // MODE_WEATHER_H
