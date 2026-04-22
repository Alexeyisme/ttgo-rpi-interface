# TTGO Transport Protocol

## Primary Transport: WiFi WebSocket

The TTGO ESP32 connects to home WiFi and maintains a persistent WebSocket
connection to the RPi bridge server.

Connection: ws://homunculus.local:8765 (TTGO is WS client, RPi bridge is WS server)

Each WS text frame = one JSON object. Same JSON schema as the serial protocol below.
No newline framing needed (each frame is a complete message).

Firmware: firmware/ws_transport.h
  - WiFi credentials: firmware/wifi_config.h (gitignored, see wifi_config.h.example)
  - WS host: WS_HOST macro (default: homunculus.local)
  - WS port: WS_PORT macro (default: 8765)
  - Auto-reconnect: 3s interval
  - Heartbeat: ping every 15s

Bridge: bridge/ws_transport.py
  - WS server on 0.0.0.0:8765 (configurable via WS_PORT env var)
  - Accepts exactly one TTGO client at a time
  - Reconnects gracefully when TTGO drops

Usage:
  python3 ttgo_bridge.py                   # default: WebSocket
  python3 ttgo_bridge.py --transport ws    # explicit WebSocket
  python3 ttgo_bridge.py --transport serial # USB serial fallback

---

## Legacy Transport: USB Serial (fallback)

Serial protocol (newline-delimited JSON)

Transport
- Baud: 460800
- Framing: one JSON object per line, terminated by '\n'

TTGO → Raspberry Pi (events)
- {"event":"device_ready"}
- {"event":"mode_changed","mode":<int>}   where mode indices are:
    0=stats, 1=spotify, 2=weather, 3=image
- {"event":"ptt_start"}
- {"event":"ptt_stop"}

Raspberry Pi → TTGO (packets)
- Stats:
  {"type":"stats","cpu":<float>,"ram":<float>,"ram_total":<float>,"temp":<float>,"disk":<float>,
   "uptime_sec":<int>,"load1":<float>,"load5":<float>,"load15":<float>}

- Spotify:
  {"type":"spotify","track":"...","artist":"...","playing":<bool>,
   "progress_pct":<int>,"progress_sec":<int>,"duration_sec":<int>}

- Weather:
  {"type":"weather","temp_out":<float>,"hum_out":<float>,"temp_in":<float>,"hum_in":<float>,"aqi":<int>}

- Image:
  {"type":"image","jpeg_b64":"<base64>"}

- Remote control:
  {"type":"set_mode","mode":<int>}

- Ack overlay:
  {"type":"ack","text":"..."}

Notes
- Firmware routes incoming packets only when type matches the currently active mode.
- The bridge pushes all lightweight modes on their own intervals, regardless of what the TTGO is showing.
