TTGO T-Display Hermes Satellite (ESP32 + ST7789)

This repository contains two parts:
1) Firmware (PlatformIO / Arduino C++) running on the TTGO T-Display (ESP32)
2) Bridge daemon (Python) running on Raspberry Pi (reads system/HA/Spotify/webcam, sends newline-delimited JSON over USB serial)

Hardware
- TTGO T-Display (ESP32 + ST7789 135x240)
- Connected to Raspberry Pi via USB serial (e.g. /dev/ttyACM0)
- Buttons:
  - BTN1 (top): cycles display modes
  - BTN2 (bottom, hold): Push-to-Talk (PTT)

Quick start (Raspberry Pi)
- Install Python deps:  python3 -m pip install -r bridge/requirements.txt
- Configure environment variables (see .env.example)
- Run bridge:
    cd bridge
    python3 ttgo_bridge.py --debug --env-file ../.env

Quick start (ESP32 firmware)
- Install PlatformIO
- Build/upload from repository root:
    pio run
    pio run -t upload

Serial protocol
- Documented in docs/serial-protocol.md

Safety / secrets
- Do NOT commit real credentials. Copy .env.example to .env locally.

