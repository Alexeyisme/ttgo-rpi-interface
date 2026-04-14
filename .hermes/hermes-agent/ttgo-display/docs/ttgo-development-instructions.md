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
1) Serial framing limits (most common failure)
- Firmware UART JSON input uses a fixed line buffer.
- If the base64 payload is too large/truncated/corrupted, TTGO can fail to parse or can’t open JPEG.
- During this session we learned that higher baud rates can amplify line-integrity problems, so payload must fit reliably.
- Bridge keeps payloads small:
  - MAX_JPEG_BYTES=11000 and adaptive JPEG quality in bridge/data_collectors.py

2) ArduinoJson document sizing (firmware)
- Firmware uses StaticJsonDocument<SERIAL_JSON_DOC_SIZE> to allow decoding image packets.

3) JPEGDEC -> TFT_eSPI RGB565 endianness
- If decoded images look “trippy” / wrong especially in bright areas, RGB565 endianness
  can be mismatched.
- Current fix: JPEGDEC draw callback byte-swaps each 16-bit pixel before pushImage().

Debugging what failed
- TTGO now can show red errors and (when failing) also prints sizes:
  - src:<base64_len> jpeg:<decoded_jpeg_bytes>
  This helps distinguish:
  - base64 corruption/truncation (jpegLen too small)
  - JPEGDEC “openRAM” failing due to incomplete bytes

What we changed for reliability in this session
- Base64 decode made stricter in firmware (stop at '=' and fail fast on invalid chars).
- Increased firmware headroom for JSON/base64/jpg buffers while testing high baud rates.
- Camera blinking fix:
  - Bridge now captures/sends an image exactly once when TTGO enters image mode.
  - Periodic push loop no longer triggers camera captures for stats/spotify/weather.

What to check when image fails
- RPi side logs (bridge): WebcamCollector capture + payload size
- TTGO side: does it advance past “Waiting for image...” and/or show red error text?

After changing code
- Flash firmware with ./scripts/flash_and_restart.sh
- Ensure the bridge service restarts (script does it automatically)
