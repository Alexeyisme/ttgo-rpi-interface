#ifndef MODE_SPOTIFY_H
#define MODE_SPOTIFY_H

#include "mode_base.h"

// ─────────────────────────────────────────────────────────────────────────────
// ModeSpotify — Spotify now playing display.
//
// Layout:
//   [ ♪ Spotify              ● ]
//   ─────────────────────────────
//   Kind of Blue
//   Miles Davis
//   ─────────────────────────────
//   ▶  ──────●────────────  2:14
//   ─────────────────────────────
//   [  PLAYING  ]  or  [ PAUSED ]
// ─────────────────────────────────────────────────────────────────────────────
class ModeSpotify : public IDisplayMode {
public:
    const char* typeName()    const override { return "spotify"; }
    const char* displayName() const override { return "Spotify"; }

    void onEnter(TFT_eSPI& tft) override {
        tft.fillScreen(COL_BG);
        drawHeader(tft, "Now Playing", _connected);
        _drawAll(tft);
    }

    void onData(JsonObject data, TFT_eSPI& tft) override {
        _track    = data["track"].as<String>();
        _artist   = data["artist"].as<String>();
        _playing  = data["playing"] | false;
        _progPct  = data["progress_pct"] | 0;
        _durationSec = data["duration_sec"] | 0;
        _progressSec = data["progress_sec"] | 0;
        _staleAt  = millis() + STALE_DATA_MS;
        _connected = true;
        drawHeader(tft, "Now Playing", _connected);
        _drawAll(tft);
    }

    void onConnected(bool connected, TFT_eSPI& tft) override {
        _connected = connected;
        drawHeader(tft, "Now Playing", _connected);
    }

private:
    String  _track  = "Nothing playing";
    String  _artist = "";
    bool    _playing = false;
    int     _progPct = 0;
    int     _durationSec = 0;
    int     _progressSec = 0;
    bool    _connected = false;
    unsigned long _staleAt = 0;

    void _drawAll(TFT_eSPI& tft) {
        bool stale = (_staleAt > 0 && millis() > _staleAt);

        // Clear content area
        tft.fillRect(0, 24, SCREEN_W, SCREEN_H - 24, COL_BG);

        // Track name (large, wrapped at 2 lines)
        tft.setTextFont(4);
        tft.setTextSize(1);
        tft.setTextColor(TFT_WHITE, COL_BG);
        String t = truncate(_track, 14);
        int tw = tft.textWidth(t.c_str());
        tft.setCursor((SCREEN_W - tw) / 2, 32);
        tft.print(t.c_str());

        // Artist name (smaller)
        tft.setTextFont(2);
        tft.setTextColor(COL_CYAN, COL_BG);
        String a = truncate(_artist, 20);
        tw = tft.textWidth(a.c_str());
        tft.setCursor((SCREEN_W - tw) / 2, 68);
        tft.print(a.c_str());

        // Divider
        tft.drawFastHLine(10, 86, SCREEN_W - 20, COL_HEADER);

        // Progress bar (y=96)
        int barX = 14, barY = 100, barW = SCREEN_W - 28;
        tft.fillRect(barX, barY, barW, 4, COL_BAR_BG);
        int filled = (int)(_progPct / 100.0f * barW);
        tft.fillRect(barX, barY, filled, 4, COL_GREEN);
        // Progress dot
        tft.fillCircle(barX + filled, barY + 2, 4, TFT_WHITE);

        // Time labels
        {
            char tbuf[8], dbuf[8];
            int pm = _progressSec / 60, ps = _progressSec % 60;
            int dm = _durationSec  / 60, ds = _durationSec  % 60;
            snprintf(tbuf, sizeof(tbuf), "%d:%02d", pm, ps);
            snprintf(dbuf, sizeof(dbuf), "%d:%02d", dm, ds);
            tft.setTextFont(1);
            tft.setTextColor(COL_LABEL, COL_BG);
            tft.setCursor(barX, barY + 10);
            tft.print(tbuf);
            int dw = tft.textWidth(dbuf);
            tft.setCursor(barX + barW - dw, barY + 10);
            tft.print(dbuf);
        }

        // Divider
        tft.drawFastHLine(10, 125, SCREEN_W - 20, COL_HEADER);

        // Play/Pause badge
        const char* badge = _playing ? "PLAYING" : "PAUSED";
        uint16_t badgeColor = _playing ? COL_GREEN : COL_YELLOW;
        tft.fillRoundRect(30, 132, SCREEN_W - 60, 22, 4, badgeColor);
        tft.setTextFont(2);
        tft.setTextColor(TFT_BLACK, badgeColor);
        int bw = tft.textWidth(badge);
        tft.setCursor((SCREEN_W - bw) / 2, 136);
        tft.print(badge);

        // Play/pause icon
        if (_playing) {
            // Two vertical bars (pause would be ▶)
            tft.fillRect(18, 133, 4, 20, COL_GREEN);
            tft.fillRect(24, 133, 4, 20, COL_GREEN);
        } else {
            // Triangle ▶
            for (int i = 0; i < 10; i++) {
                tft.drawFastVLine(18 + i, 133 + i / 2, 20 - i, COL_YELLOW);
            }
        }

        if (stale) {
            drawCentered(tft, "-- stale --", 165, COL_STALE);
        }
    }
};

#endif // MODE_SPOTIFY_H
