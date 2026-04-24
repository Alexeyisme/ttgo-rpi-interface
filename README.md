TTGO T-Display Hermes Satellite (ESP32 + ST7789)

This repository contains two parts:
1) Firmware (PlatformIO / Arduino C++) running on the TTGO T-Display (ESP32)
2) Bridge daemon (Python) running on Raspberry Pi (reads system/HA/Spotify/webcam, sends newline-delimited JSON over USB serial)

Hardware
- TTGO T-Display (ESP32 + ST7789 135x240)
- Connects to the bridge over WiFi WebSocket (USB serial only used for initial flash / fallback)
- Buttons:
  - GPIO35 (top): unused (physically damaged)
  - GPIO0 (bottom): cycles display modes (active LOW)

Quick start (Raspberry Pi)
- Install Python deps:  python3 -m pip install -r bridge/requirements.txt
- Configure environment variables (see .env.example)
- Run bridge:
    cd bridge
    python3 ttgo_bridge.py --debug --env-file ../.env (optional; mainly for local/dev)

Quick start (ESP32 firmware)
- Install PlatformIO
- From repository root (TTGO connected as /dev/ttyACM0):
    pio run -e lilygo-t-display
    pio run -e lilygo-t-display -t upload

Note: this repo keeps firmware sources in ./firmware, but PlatformIO expects ./src by default; a symlink ./src -> ./firmware is used for local builds.

Serial protocol
- Documented in docs/serial-protocol.md

Safety / secrets
- Do NOT commit real credentials. Copy .env.example to .env locally.

