Bridge daemon (Raspberry Pi)

This folder contains the Python daemon that:
- Opens the serial device connected to the TTGO (default: /dev/ttyACM0)
- Receives TTGO events (mode_changed, ptt_start/ptt_stop)
- Periodically sends display updates as newline-delimited JSON
- On PTT: records audio and sends it to Telegram (Hermes handles the message on its side)

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
