TTGO T-Display Hermes Satellite — development instructions

Repo layout
- Firmware (ESP32, PlatformIO): firmware/
- Bridge daemon (Raspberry Pi, Python): bridge/
- For local PlatformIO builds, the repo uses a symlink: src -> firmware

Fast loop commands
- Build+upload+restart bridge (recommended):
  ./scripts/flash_and_restart.sh
- Same, but tail bridge journal logs:
  ./scripts/flash_and_restart.sh --logs 20

Common knobs / pitfalls (image/webcam mode)
1) Serial framing limits
- Firmware UART JSON input uses a fixed line buffer.
- If the base64 payload is too large, deserializeJson() may fail, and the TTGO stays on:
  “Waiting for image...”.
- Bridge keeps payloads small:
  - MAX_JPEG_BYTES=11000 and adaptive JPEG quality in bridge/data_collectors.py

2) ArduinoJson document sizing (firmware)
- Firmware uses StaticJsonDocument<SERIAL_JSON_DOC_SIZE> to ensure image packets can parse.

3) JPEGDEC -> TFT_eSPI RGB565 endianness
- If decoded images look “trippy” / wrong especially in bright areas, RGB565 endianness
  can be mismatched.
- Current fix: JPEGDEC draw callback byte-swaps each 16-bit pixel before pushImage().

What to check when image fails
- RPi side logs (bridge): WebcamCollector capture + payload size
- TTGO side: does it advance past “Waiting for image...” and/or show red error text?

After changing code
- Flash firmware with ./scripts/flash_and_restart.sh
- Ensure the bridge service restarts (script does it automatically)
