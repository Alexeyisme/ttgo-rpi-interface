#ifndef MODE_STATS_H
#define MODE_STATS_H

#include "mode_base.h"

// ─────────────────────────────────────────────────────────────────────────────
// ModeStats — RPi system statistics display.
//
// Screen layout (135×240):
//   [ RPi Stats              ● ]   ← header bar (22px)
//   CPU  ████░░░░░  12.3%          ← bar + value
//   RAM  ██████░░░  68.0%
//   TEMP            41.2°C
//   DISK            18.4 GB
//   ─────────────────────────
//   Homunculus
//   12:34 PM
// ─────────────────────────────────────────────────────────────────────────────
class ModeStats : public IDisplayMode {
public:
    const char* typeName()    const override { return "stats"; }
    const char* displayName() const override { return "RPi Stats"; }

    void onEnter(TFT_eSPI& tft) override {
        tft.fillScreen(COL_BG);
        drawHeader(tft, "RPi Stats", _connected);
        _drawSkeleton(tft);
        _drawValues(tft);
    }

    void onData(JsonObject data, TFT_eSPI& tft) override {
        _cpu    = data["cpu"]  | 0.0f;
        _ram    = data["ram"]  | 0.0f;   // MB free
        _temp   = data["temp"] | 0.0f;   // °C
        _disk   = data["disk"] | 0.0f;   // GB free
        _ramTot = data["ram_total"] | 1000.0f;
        _uptime  = (unsigned long)(data["uptime_sec"] | 0);
        _load1   = (float)(data["load1"]  | 0.0f);
        _load5   = (float)(data["load5"]  | 0.0f);
        _load15  = (float)(data["load15"] | 0.0f);
        _staleAt = millis() + STALE_DATA_MS;
        _connected = true;
        drawHeader(tft, "RPi Stats", _connected);
        _drawValues(tft);
    }

    void onConnected(bool connected, TFT_eSPI& tft) override {
        _connected = connected;
        drawHeader(tft, "RPi Stats", _connected);
    }

private:
    float _cpu = 0, _ram = 0, _temp = 0, _disk = 0, _ramTot = 1000;
    float _load1 = 0, _load5 = 0, _load15 = 0;
    unsigned long _uptime = 0;
    bool  _connected = false;
    unsigned long _staleAt = 0;

    void _drawSkeleton(TFT_eSPI& tft) {
        // Label column
        tft.setTextFont(2);
        tft.setTextSize(1);
        tft.setTextColor(COL_LABEL, COL_BG);
        tft.setCursor(4, 30);  tft.print("CPU");
        tft.setCursor(4, 65);  tft.print("RAM");
        tft.setCursor(4, 105); tft.print("TEMP");
        tft.setCursor(4, 130); tft.print("DISK");
        // Divider
        tft.drawFastHLine(0, 155, SCREEN_W, COL_HEADER);
    }

    void _drawValues(TFT_eSPI& tft) {
        bool stale = (_staleAt > 0 && millis() > _staleAt);
        uint16_t vc = stale ? COL_STALE : COL_VALUE;

        // CPU bar + value
        tft.fillRect(4, 46, SCREEN_W - 8, PROGRESS_BAR_H, COL_BAR_BG);
        drawBar(tft, 4, 46, SCREEN_W - 8, _cpu / 100.0f, COL_BAR_CPU);
        {
            char buf[12];
            snprintf(buf, sizeof(buf), "%.1f%%", _cpu);
            tft.fillRect(0, 28, SCREEN_W, 16, COL_BG);
            tft.setTextColor(vc, COL_BG);
            tft.setTextFont(2);
            tft.setCursor(4, 28); tft.print("CPU");
            tft.setCursor(70, 28); tft.print(buf);
        }

        // RAM bar + value
        float ramPct = (_ramTot > 0) ? (1.0f - _ram / _ramTot) : 0.0f;
        tft.fillRect(4, 81, SCREEN_W - 8, PROGRESS_BAR_H, COL_BAR_BG);
        drawBar(tft, 4, 81, SCREEN_W - 8, ramPct, COL_BAR_RAM);
        {
            char buf[16];
            snprintf(buf, sizeof(buf), "%d MB", (int)_ram);
            tft.fillRect(0, 63, SCREEN_W, 16, COL_BG);
            tft.setTextColor(vc, COL_BG);
            tft.setTextFont(2);
            tft.setCursor(4, 63); tft.print("RAM");
            tft.setCursor(70, 63); tft.print(buf);
        }

        // Temp
        {
            char buf[12];
            snprintf(buf, sizeof(buf), "%.1f C", _temp);
            tft.fillRect(0, 103, SCREEN_W, 16, COL_BG);
            tft.setTextColor(_temp > 70 ? COL_RED : vc, COL_BG);
            tft.setTextFont(2);
            tft.setCursor(4, 103); tft.print("TEMP");
            tft.setCursor(70, 103); tft.print(buf);
        }

        // Disk
        {
            char buf[16];
            snprintf(buf, sizeof(buf), "%.1f GB", _disk);
            tft.fillRect(0, 128, SCREEN_W, 16, COL_BG);
            tft.setTextColor(_disk < 2.0f ? COL_RED : vc, COL_BG);
            tft.setTextFont(2);
            tft.setCursor(4, 128); tft.print("DISK");
            tft.setCursor(70, 128); tft.print(buf);
        }

        // Uptime + load at bottom
        tft.fillRect(0, 160, SCREEN_W, 80, COL_BG);
        tft.setTextFont(2);

        // Uptime (compact): hours if >=1h, otherwise minutes.
        if (_uptime > 0) {
            unsigned long minutes = _uptime / 60;
            unsigned long hours   = minutes / 60;
            unsigned long mins2   = minutes % 60;

            char ubuf[16];
            if (hours >= 1) {
                snprintf(ubuf, sizeof(ubuf), "%luh %02lu", hours, mins2);
            } else {
                snprintf(ubuf, sizeof(ubuf), "%llum", minutes);
            }
            tft.setTextColor(COL_CYAN, COL_BG);
            drawCentered(tft, ubuf, 168, COL_CYAN);
        } else {
            tft.setTextColor(COL_CYAN, COL_BG);
            drawCentered(tft, "uptime ?", 168, COL_CYAN);
        }

        // Load averages (1m and 5m)
        {
            char lbuf[24];
            snprintf(lbuf, sizeof(lbuf), "L %.1f %.1f", _load1, _load5);
            tft.setTextColor(COL_LABEL, COL_BG);
            drawCentered(tft, lbuf, 190, COL_LABEL);
        }

        if (stale) {
            drawCentered(tft, "-- stale --", 210, COL_STALE);
        }
    }
};

#endif // MODE_STATS_H
