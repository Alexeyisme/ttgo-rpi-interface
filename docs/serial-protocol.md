Serial protocol (newline-delimited JSON)

Transport
- Baud: 115200
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
