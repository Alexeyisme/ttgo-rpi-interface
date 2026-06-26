Bridge daemon (Raspberry Pi)

This folder contains the Python daemon that:
- Listens for a WebSocket connection from the TTGO (default: ws://0.0.0.0:8765); USB serial is available as a fallback via --transport serial
- Receives TTGO events (device_ready, mode_changed)
- Periodically sends display updates (stats, spotify, weather, webcam image) as JSON frames

Quick start
1) Create env file
   cp .env.example .env
   (Fill only the values you need.)

2) Install python deps
   python3 -m pip install -r requirements.txt

3) Run (foreground)
   python3 ttgo_bridge.py --debug

Systemd
- Use bridge/ttgo-bridge.service as a template.
- Copy your secrets to /etc/ttgo-display/ttgo-bridge.env (or edit EnvironmentFile= in the unit).

Protocol contract (heartbeat & stale-data behavior)
- Transport: newline-delimited JSON (every JSON object MUST end with '\n').
- Raspberry Pi -> TTGO:
  - Normal payloads have "type" = stats|spotify|weather|image.
  - Keepalive payload: {"type":"heartbeat","ts":<unix_seconds>}
- Heartbeat requirements:
  - The bridge sends heartbeat periodically (default interval is configured in bridge/ttgo_bridge.py via HEARTBEAT_INTERVAL).
  - Heartbeats are sent independent of the current TTGO UI mode.
- Firmware stale-data behavior (contract):
  - The firmware uses heartbeat arrival to decide that the data pipeline is still alive.
  - If heartbeat messages stop arriving for longer than the firmware's watchdog window, the UI must treat the display as stale/offline (e.g., show a connected/offline indicator or stale banner) until fresh keepalives resume.
  - Mode payload routing: the firmware should only render/consume payload types that match the currently active mode, but heartbeat should keep freshness/connection state valid.
