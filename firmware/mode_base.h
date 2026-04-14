#ifndef MODE_BASE_H
#define MODE_BASE_H

#include <TFT_eSPI.h>
#include <ArduinoJson.h>
#include "config.h"

// ─────────────────────────────────────────────────────────────────────────────
// IDisplayMode — abstract interface for all display modes.
//
// To add a new mode:
//   1. Create mode_mymode.h / mode_mymode.cpp implementing this interface.
//   2. Register it in DisplayManager::begin() in display_manager.cpp.
//   3. No other changes needed.
// ─────────────────────────────────────────────────────────────────────────────
class IDisplayMode {
public:
    virtual ~IDisplayMode() = default;

    // Called once when the user switches TO this mode.
    // Should draw the full screen skeleton (headers, labels, placeholders).
    virtual void onEnter(TFT_eSPI& tft) = 0;

    // Called when a JSON packet whose "type" matches typeName() arrives.
    // Only called while this mode is the active mode.
    virtual void onData(JsonObject data, TFT_eSPI& tft) = 0;

    // Called every ANIMATION_TICK_MS for time-based animations (clocks, etc.).
    // Most modes can leave this as a no-op.
    virtual void onTick(TFT_eSPI& tft) {}

    // Called when the RPi connection is lost or regained.
    virtual void onConnected(bool connected, TFT_eSPI& tft) {}

    // The JSON "type" string this mode handles, e.g. "stats".
    virtual const char* typeName() const = 0;

    // Human-readable name for the header bar, e.g. "RPi Stats".
    virtual const char* displayName() const = 0;

protected:
    // ── Shared drawing helpers ────────────────────────────────────────────────

    // Draw a header bar at the top of the screen.
    void drawHeader(TFT_eSPI& tft, const char* title, bool connected = true) {
        tft.fillRect(0, 0, SCREEN_W, 22, COL_HEADER);
        tft.setTextColor(COL_HEADER_TXT, COL_HEADER);
        tft.setTextSize(1);
        tft.setTextFont(2);
        tft.setCursor(4, 5);
        tft.print(title);
        // Connection dot — top right
        uint16_t dotColor = connected ? COL_GREEN : COL_RED;
        tft.fillCircle(SCREEN_W - 8, 11, 4, dotColor);
    }

    // Draw a labeled value row: "LABEL    value"
    void drawRow(TFT_eSPI& tft, int y, const char* label, const char* value,
                 uint16_t valColor = COL_VALUE) {
        tft.setTextFont(2);
        tft.setTextSize(1);
        tft.setTextColor(COL_LABEL, COL_BG);
        tft.fillRect(0, y, SCREEN_W, 18, COL_BG);
        tft.setCursor(4, y + 2);
        tft.print(label);
        tft.setTextColor(valColor, COL_BG);
        tft.setCursor(70, y + 2);
        tft.print(value);
    }

    // Draw a horizontal progress bar.
    // x,y = top-left; w = total width; pct = 0.0..1.0
    void drawBar(TFT_eSPI& tft, int x, int y, int w, float pct, uint16_t fillColor) {
        int filled = (int)(pct * w);
        filled = filled < 0 ? 0 : (filled > w ? w : filled);
        tft.fillRect(x, y, filled, PROGRESS_BAR_H, fillColor);
        tft.fillRect(x + filled, y, w - filled, PROGRESS_BAR_H, COL_BAR_BG);
    }

    // Center-print a string on a given y coordinate.
    void drawCentered(TFT_eSPI& tft, const char* text, int y,
                      uint16_t color = COL_VALUE, uint8_t font = 2) {
        tft.setTextFont(font);
        tft.setTextSize(1);
        tft.setTextColor(color, COL_BG);
        int16_t tw = tft.textWidth(text);
        tft.setCursor((SCREEN_W - tw) / 2, y);
        tft.print(text);
    }

    // Truncate a String to maxLen chars (adds "…" if truncated).
    String truncate(const String& s, int maxLen) {
        if ((int)s.length() <= maxLen) return s;
        return s.substring(0, maxLen - 1) + char(0x85);  // ellipsis-like char
    }
};

#endif // MODE_BASE_H
