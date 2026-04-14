#!/usr/bin/env python3
"""
ttgo_bridge.py — Main daemon for TTGO T-Display satellite.

Coordinates:
  - SerialTransport: reads button/PTT events, sends display data
  - DataCollectors: StatsCollector, SpotifyCollector, WeatherCollector, WebcamCollector
  - VoiceHandler: arecord + Whisper + Telegram dispatch on PTT

Mode order must match MODE_* constants in firmware config.h:
  0: stats
  1: spotify
  2: weather
  3: image

Usage:
    python3 ttgo_bridge.py
    python3 ttgo_bridge.py --debug
"""

import argparse
import logging
import os
import signal
import sys
import threading
import time
from pathlib import Path

# Ensure we can import sibling modules regardless of cwd
sys.path.insert(0, str(Path(__file__).parent))

from serial_transport import SerialTransport
from data_collectors  import StatsCollector, SpotifyCollector, WeatherCollector, WebcamCollector
from voice_handler    import VoiceHandler

logger = logging.getLogger(__name__)

# ── Push intervals per mode (seconds) ────────────────────────────────────────
PUSH_INTERVAL = {
    "stats":   5,
    "spotify": 5,
    "weather": 10,

    # Image payload is heavy and we ONLY want to capture/send it when
    # TTGO enters image mode (see _on_serial_event -> mode_changed).
    # So we keep the entry here for completeness but periodic pushing is disabled below.
    "image":   10**9,
}

# Heartbeat interval — send a tiny keepalive when the mode's push interval
# exceeds the firmware's stale-data watchdog (15 s).
HEARTBEAT_INTERVAL = 10  # seconds

# Mode index → type string (must match firmware config.h MODE_* order)
MODE_TYPES = ["stats", "spotify", "weather", "image"]


class TTGOBridge:
    def __init__(self, serial_port: str = "/dev/ttyACM0", baud: int = 460800):
        self._current_mode = 0
        self._running      = False

        # Data collectors keyed by mode type
        self._collectors = {
            "stats":   StatsCollector(),
            "spotify": SpotifyCollector(),
            "weather": WeatherCollector(),
            "image":   WebcamCollector(),
        }

        self._voice = VoiceHandler(on_ack=self._send_ack)
        self._transport = SerialTransport(port=serial_port, baud=baud, on_event=self._on_serial_event)
        self._last_push: dict = {t: 0.0 for t in MODE_TYPES}
        self._last_heartbeat = 0.0

        self._push_thread: threading.Thread = None
        self._stop_event = threading.Event()

    # ── Public ───────────────────────────────────────────────────────────────

    def start(self):
        self._running = True
        self._transport.start()

        self._push_thread = threading.Thread(
            target=self._push_loop, daemon=True, name="push-loop"
        )
        self._push_thread.start()

        logger.info("TTGO Bridge started. Mode: %s", MODE_TYPES[self._current_mode])

    def wait(self):
        """Block until stop() is called."""
        self._stop_event.wait()

    def stop(self):
        self._running = False
        self._transport.stop()
        self._stop_event.set()
        logger.info("TTGO Bridge stopped")

    # ── Serial event handler (called from read thread) ───────────────────────

    def _on_serial_event(self, obj: dict):
        event = obj.get("event", "")
        logger.debug("Serial event: %s", event)

        if event == "device_ready":
            logger.info("TTGO device ready — pushing current mode data")
            self._push_now(MODE_TYPES[self._current_mode])

        elif event == "btn1_press":
            # TTGO already changed mode; we just need to know which one.
            # Firmware sends mode_changed with the new index.
            pass

        elif event == "mode_changed":
            new_idx = obj.get("mode", 0)
            if 0 <= new_idx < len(MODE_TYPES):
                old_mode = MODE_TYPES[self._current_mode]
                self._current_mode = new_idx
                new_mode = MODE_TYPES[new_idx]
                logger.info("Mode changed: %s → %s", old_mode, new_mode)
                # If TTGO enters image mode, capture/send exactly once.
                if new_mode == "image":
                    self._collectors["image"].invalidate_cache()
                    self._push_now("image")
                else:
                    # Push data for non-image modes immediately.
                    self._push_now(new_mode)

        elif event == "ptt_start":
            logger.info("PTT start")
            self._voice.on_ptt_start()

        elif event == "ptt_stop":
            logger.info("PTT stop")
            self._voice.on_ptt_stop()

    def set_mode(self, mode_idx: int):
        """Remotely switch display mode via serial command."""
        if 0 <= mode_idx < len(MODE_TYPES):
            old_mode = MODE_TYPES[self._current_mode]
            self._current_mode = mode_idx
            new_mode = MODE_TYPES[mode_idx]
            logger.info("Remote mode switch: %s → %s", old_mode, new_mode)
            self._transport.send({"type": "set_mode", "mode": mode_idx})
            if new_mode == "image":
                self._collectors["image"].invalidate_cache()
                time.sleep(0.3)  # let firmware process set_mode
                self._push_now("image")
            else:
                time.sleep(0.3)  # let firmware process set_mode
                self._push_now(new_mode)
            return

        logger.warning("set_mode: invalid mode_idx=%s", mode_idx)


    # ── Data push loop ────────────────────────────────────────────────────────

    def _push_loop(self):
        while self._running:
            now = time.monotonic()

            # Push ALL lightweight modes on their own intervals so the
            # firmware always has fresh data regardless of which mode the
            # TTGO is displaying.  (Button events are unreliable over
            # serial, so the bridge can't trust _current_mode.)
            for mode in MODE_TYPES:
                # Image payload is disabled in periodic push loop.

                interval = PUSH_INTERVAL.get(mode, 5)
                if now - self._last_push[mode] >= interval:
                    self._push_now(mode)

            time.sleep(1.0)

    def _push_now(self, mode: str):
        collector = self._collectors.get(mode)
        if collector is None:
            return

        try:
            data = collector.collect()
            if data is not None:
                self._transport.send(data)
                self._last_push[mode] = time.monotonic()
                logger.debug("Pushed %s data", mode)
        except Exception as e:
            logger.warning("Push error for mode %s: %s", mode, e)

    def _send_ack(self, text: str):
        self._transport.send({"type": "ack", "text": text})


# ── Entry point ───────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="TTGO T-Display Bridge")
    parser.add_argument("--debug", action="store_true", help="Enable debug logging")
    args = parser.parse_args()

    level = logging.DEBUG if args.debug else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )

    # Load .env before anything else
    env_file = Path.home() / ".hermes" / ".env"
    if env_file.exists():
        for line in env_file.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, _, v = line.partition("=")
                os.environ.setdefault(k.strip(), v.strip())

    bridge = TTGOBridge()

    def _shutdown(sig, frame):
        logger.info("Signal %s received — shutting down", sig)
        bridge.stop()

    signal.signal(signal.SIGINT,  _shutdown)
    signal.signal(signal.SIGTERM, _shutdown)

    bridge.start()
    bridge.wait()
    logger.info("Bridge exited cleanly")


if __name__ == "__main__":
    main()
