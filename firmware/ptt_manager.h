#ifndef PTT_MANAGER_H
#define PTT_MANAGER_H

#include <TFT_eSPI.h>
#include "config.h"

// ─────────────────────────────────────────────────────────────────────────────
// PTTManager — Push-to-Talk overlay and animated waveform.
//
// While Button2 is held:
//   - Draws a full-screen "Listening..." overlay with animated sound wave bars.
//   - Sends {"event":"ptt_start"} once on press.
//   - Sends {"event":"ptt_stop"} once on release.
//
// The DisplayManager calls tick() every ANIMATION_TICK_MS while active.
// ─────────────────────────────────────────────────────────────────────────────

#define PTT_NUM_BARS    16          // Number of waveform bars
#define PTT_BAR_W       5           // Bar width in pixels
#define PTT_BAR_GAP     2           // Gap between bars
#define PTT_BAR_Y_CENTER 160        // Vertical center of waveform
#define PTT_BAR_MAX_H   50          // Maximum bar height in pixels
#define PTT_BAR_MIN_H   4

class PTTManager {
public:
    PTTManager() : _active(false), _lastTick(0) {
        for (int i = 0; i < PTT_NUM_BARS; i++) _barH[i] = PTT_BAR_MIN_H;
    }

    bool isActive() const { return _active; }

    void start(TFT_eSPI& tft) {
        _active = true;
        _drawOverlay(tft);
    }

    void stop(TFT_eSPI& tft) {
        _active = false;
        // Caller (main.cpp) will redraw the current mode after this.
    }

    // Call every loop() when active — redraws waveform on tick interval.
    void tick(TFT_eSPI& tft) {
        if (!_active) return;
        unsigned long now = millis();
        if (now - _lastTick < ANIMATION_TICK_MS) return;
        _lastTick = now;
        _animateBars(tft);
    }

private:
    bool _active;
    unsigned long _lastTick;
    uint8_t _barH[PTT_NUM_BARS];

    void _drawOverlay(TFT_eSPI& tft) {
        tft.fillScreen(COL_PTT_BG);

        // Mic icon (simple circle + line)
        tft.fillCircle(SCREEN_W / 2, 55, 20, COL_PTT_WAVE);
        tft.fillRect(SCREEN_W / 2 - 6, 35, 12, 40, COL_PTT_BG);
        tft.fillRoundRect(SCREEN_W / 2 - 10, 38, 20, 34, 8, COL_PTT_WAVE);

        // Mic stand
        tft.drawFastHLine(SCREEN_W / 2 - 14, 90, 28, COL_PTT_WAVE);
        tft.drawFastVLine(SCREEN_W / 2, 90, 18, COL_PTT_WAVE);

        // Label
        tft.setTextFont(4);
        tft.setTextColor(TFT_WHITE, COL_PTT_BG);
        int tw = tft.textWidth("Listening...", 4);
        tft.setCursor((SCREEN_W - tw) / 2, 112);
        tft.print("Listening...");

        // Initial bars
        _animateBars(tft);
    }

    void _animateBars(TFT_eSPI& tft) {
        int totalW = PTT_NUM_BARS * (PTT_BAR_W + PTT_BAR_GAP) - PTT_BAR_GAP;
        int startX = (SCREEN_W - totalW) / 2;

        for (int i = 0; i < PTT_NUM_BARS; i++) {
            // Smooth toward a random target with some momentum
            int target = PTT_BAR_MIN_H + random(0, PTT_BAR_MAX_H - PTT_BAR_MIN_H);
            _barH[i] = (_barH[i] * 3 + target) / 4;

            int x = startX + i * (PTT_BAR_W + PTT_BAR_GAP);
            int h = _barH[i];
            int y = PTT_BAR_Y_CENTER - h / 2;

            // Erase old bar area
            tft.fillRect(x, PTT_BAR_Y_CENTER - PTT_BAR_MAX_H / 2,
                         PTT_BAR_W, PTT_BAR_MAX_H, COL_PTT_BG);
            // Draw new bar with gradient-like color based on height
            uint16_t color = (h > PTT_BAR_MAX_H * 0.7f) ? COL_YELLOW : COL_PTT_WAVE;
            tft.fillRoundRect(x, y, PTT_BAR_W, h, 2, color);
        }
    }
};

#endif // PTT_MANAGER_H
