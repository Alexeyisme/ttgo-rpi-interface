#ifndef CONFIG_H
#define CONFIG_H

// ── Serial ────────────────────────────────────────────────────────────────────
#define SERIAL_BAUD_RATE 460800

// ── TFT ───────────────────────────────────────────────────────────────────────
#define TFT_ROTATION    0       // Portrait: 135 wide x 240 tall
#define SCREEN_W        135
#define SCREEN_H        240
#define TFT_BL          4       // Backlight GPIO

// ── Buttons ───────────────────────────────────────────────────────────
// NOTE: Top button (GPIO35) is broken.
// Mode cycling on GPIO0 (active LOW).
// Voice/chat control now lives on a separate USB-tethered device (ttgo-chat-controller).
#define BTN1_PIN        35      // Top button — BROKEN, unused
#define MODE_BTN_PIN    0       // Mode cycle button (GPIO0, active LOW)
#define BTN_DEBOUNCE_MS 200     // Debounce window

// ── Display modes ─────────────────────────────────────────────────────────────
#define MODE_STATS      0
#define MODE_SPOTIFY    1
#define MODE_WEATHER    2
#define MODE_IMAGE      3
#define NUM_MODES       4

// ── Timeouts / intervals ──────────────────────────────────────────────────────
#define STALE_DATA_MS       15000   // Show stale indicator after 15 s without data
#define PROGRESS_BAR_H      8       // Height of progress bars in pixels

// ── Colors (RGB565) ───────────────────────────────────────────────────────────
#define COL_BG          TFT_BLACK
#define COL_HEADER      0x04B4      // Dark teal header bar
#define COL_HEADER_TXT  TFT_WHITE
#define COL_LABEL       0x7BEF      // Light gray labels
#define COL_VALUE       TFT_WHITE
#define COL_BAR_BG      0x2104      // Dark bar background
#define COL_BAR_CPU     0x07FF      // Cyan — CPU
#define COL_BAR_RAM     0xFD20      // Orange — RAM
#define COL_BAR_DISK    0x07E0      // Green — Disk
#define COL_GREEN       0x07E0
#define COL_RED         TFT_RED
#define COL_YELLOW      TFT_YELLOW
#define COL_CYAN        TFT_CYAN
#define COL_ORANGE      0xFD20
#define COL_STALE       0x632C      // Dim orange-red for stale data

#endif // CONFIG_H
