#ifndef MODE_IMAGE_H
#define MODE_IMAGE_H

#include "mode_base.h"
// Include JPEGDEC without SD/FS.h — we only use openRAM() from RAM buffer.
#include <JPEGDEC.h>

// ─────────────────────────────────────────────────────────────────────────────
// ModeImage — full-bleed JPEG image from webcam.
//
// Receives {"type":"image","jpeg_b64":"<base64>"} from the RPi bridge.
// Decodes and blits the JPEG to fill the 135×240 screen.
// A small "CAM" label overlays the top-right corner.
// ─────────────────────────────────────────────────────────────────────────────

// Global TFT pointer used by JPEGDEC draw callback (C-style callback limitation)
static TFT_eSPI* _imgTft = nullptr;

static int _jpegDrawCallback(JPEGDRAW* pDraw) {
    if (!_imgTft) return 0;
    _imgTft->pushImage(pDraw->x, pDraw->y, pDraw->iWidth, pDraw->iHeight, pDraw->pPixels);
    return 1;
}

// Simple base64 decode table
static const int8_t _b64Table[256] = {
    -1,-1,-1,-1,-1,-1,-1,-1,-1,-1,-1,-1,-1,-1,-1,-1,
    -1,-1,-1,-1,-1,-1,-1,-1,-1,-1,-1,-1,-1,-1,-1,-1,
    -1,-1,-1,-1,-1,-1,-1,-1,-1,-1,-1,62,-1,-1,-1,63,
    52,53,54,55,56,57,58,59,60,61,-1,-1,-1,-1,-1,-1,
    -1, 0, 1, 2, 3, 4, 5, 6, 7, 8, 9,10,11,12,13,14,
    15,16,17,18,19,20,21,22,23,24,25,-1,-1,-1,-1,-1,
    -1,26,27,28,29,30,31,32,33,34,35,36,37,38,39,40,
    41,42,43,44,45,46,47,48,49,50,51,-1,-1,-1,-1,-1,
    -1,-1,-1,-1,-1,-1,-1,-1,-1,-1,-1,-1,-1,-1,-1,-1,
    -1,-1,-1,-1,-1,-1,-1,-1,-1,-1,-1,-1,-1,-1,-1,-1,
    -1,-1,-1,-1,-1,-1,-1,-1,-1,-1,-1,-1,-1,-1,-1,-1,
    -1,-1,-1,-1,-1,-1,-1,-1,-1,-1,-1,-1,-1,-1,-1,-1,
    -1,-1,-1,-1,-1,-1,-1,-1,-1,-1,-1,-1,-1,-1,-1,-1,
    -1,-1,-1,-1,-1,-1,-1,-1,-1,-1,-1,-1,-1,-1,-1,-1,
    -1,-1,-1,-1,-1,-1,-1,-1,-1,-1,-1,-1,-1,-1,-1,-1,
    -1,-1,-1,-1,-1,-1,-1,-1,-1,-1,-1,-1,-1,-1,-1,-1
};

static size_t _b64Decode(const char* src, size_t srcLen, uint8_t* dst, size_t dstMax) {
    size_t out = 0;
    int val = 0, bits = -8;
    for (size_t i = 0; i < srcLen && out < dstMax; i++) {
        int c = _b64Table[(uint8_t)src[i]];
        if (c == -1) continue;
        val = (val << 6) + c;
        bits += 6;
        if (bits >= 0) {
            dst[out++] = (uint8_t)((val >> bits) & 0xFF);
            bits -= 8;
        }
    }
    return out;
}

#define IMG_DECODE_BUF  14336   // 14 KB decode buffer

class ModeImage : public IDisplayMode {
public:
    const char* typeName()    const override { return "image"; }
    const char* displayName() const override { return "Webcam"; }

    void onEnter(TFT_eSPI& tft) override {
        tft.fillScreen(TFT_BLACK);
        tft.setTextFont(1);
        tft.setTextColor(TFT_WHITE, TFT_BLACK);
        drawCentered(tft, "Waiting for image...", SCREEN_H / 2);
    }

    void onData(JsonObject data, TFT_eSPI& tft) override {
        const char* b64 = data["jpeg_b64"] | "";
        size_t srcLen = strlen(b64);
        if (srcLen == 0) return;

        // Decode base64 into heap buffer
        uint8_t* jpegBuf = (uint8_t*)malloc(IMG_DECODE_BUF);
        if (!jpegBuf) return;

        size_t jpegLen = _b64Decode(b64, srcLen, jpegBuf, IMG_DECODE_BUF);
        if (jpegLen == 0) { free(jpegBuf); return; }

        // Decode JPEG and blit
        _imgTft = &tft;
        JPEGDEC jpeg;
        if (jpeg.openRAM(jpegBuf, (int)jpegLen, _jpegDrawCallback)) {
            jpeg.decode(0, 0, 0);
            jpeg.close();
        }
        free(jpegBuf);
        _imgTft = nullptr;

        // CAM label overlay
        tft.fillRect(SCREEN_W - 32, 2, 30, 14, 0x0000);
        tft.setTextFont(1);
        tft.setTextColor(TFT_WHITE, TFT_BLACK);
        tft.setCursor(SCREEN_W - 30, 4);
        tft.print("CAM");
    }

    void onConnected(bool connected, TFT_eSPI& tft) override {
        if (!connected) {
            tft.fillScreen(TFT_BLACK);
            drawCentered(tft, "No signal", SCREEN_H / 2, COL_RED);
        }
    }
};

#endif // MODE_IMAGE_H
