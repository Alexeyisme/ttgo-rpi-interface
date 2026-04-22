#!/usr/bin/env python3
"""ttgo_bridge.py — Main daemon for TTGO T-Display satellite.

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

  # Optional dev override for env vars:
  python3 ttgo_bridge.py --env-file ../.env
"""

import argparse
import logging
import os
import signal
import sys
import threading
import time
from pathlib import Path
from typing import Any, Optional

# Ensure we can import sibling modules regardless of cwd
sys.path.insert(0, str(Path(__file__).parent))

from serial_transport import SerialTransport
from ws_transport import WsTransport
from data_collectors import StatsCollector, SpotifyCollector, WeatherCollector, WebcamCollector
# NOTE: VoiceHandler (and its dependencies like requests/ffmpeg/ALSA)
# are imported lazily so the bridge can be unit-tested without those
# external runtime deps.


logger = logging.getLogger(__name__)

# ── Push intervals per mode (seconds) ────────────────────────────────────────
PUSH_INTERVAL = {
    "stats": 5,
    "spotify": 5,
    "weather": 10,
    # Image payload is heavy and we ONLY want to capture/send it when
    # TTGO enters image mode (see _on_serial_event -> mode_changed).
    # So periodic pushing is effectively disabled.
    "image": 10**9,
}

# Heartbeat interval — send a tiny keepalive so firmware freshness watchdog
# doesn't trip when a mode's payload is infrequent.
HEARTBEAT_INTERVAL = 10  # seconds

# Mode index → type string (must match firmware config.h MODE_* order)
MODE_TYPES = ["stats", "spotify", "weather", "image"]


class TTGOBridge:
    def __init__(
        self,
        serial_port: str = "/dev/ttyACM0",
        baud: int = 460800,
        transport_type: str = "ws",
        collectors: Optional[dict[str, Any]] = None,
        voice: Any = None,
        transport: Optional[SerialTransport] = None,
        enable_periodic_push: bool = True,
        enable_heartbeat: bool = True,
        heartbeat_interval: float = HEARTBEAT_INTERVAL,
        mode_switch_delay: float = 0.3,
    ):
        self._current_mode = 0
        self._running = False

        self._enable_periodic_push = enable_periodic_push
        self._enable_heartbeat = enable_heartbeat
        self._heartbeat_interval = float(heartbeat_interval)
        self._mode_switch_delay = float(mode_switch_delay)

        # Data collectors keyed by mode type
        self._collectors = collectors or {
            "stats": StatsCollector(),
            "spotify": SpotifyCollector(),
            "weather": WeatherCollector(),
            "image": WebcamCollector(),
        }

        # Voice handler
        if voice is not None:
            self._voice = voice
        else:
            # Import lazily to avoid pulling requests/ffmpeg/ALSA into
            # unit tests.
            from voice_handler import VoiceHandler

            self._voice = VoiceHandler(on_ack=self._send_ack)

        # Transport
        if transport is not None:
            self._transport = transport
        elif transport_type == "serial":
            self._transport = SerialTransport(
                port=serial_port, baud=baud, on_event=self._on_serial_event
            )
        else:  # default: websocket
            ws_port = int(os.environ.get("WS_PORT", "8765"))
            self._transport = WsTransport(
                port=ws_port, on_event=self._on_serial_event
            )

        self._last_push: dict[str, float] = {t: 0.0 for t in MODE_TYPES}
        self._last_heartbeat = 0.0

        self._push_thread: Optional[threading.Thread] = None
        self._heartbeat_thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()

    # ── Public ───────────────────────────────────────────────────────────────
    def start(self):
        self._running = True
        self._transport.start()

        if self._enable_periodic_push:
            self._push_thread = threading.Thread(
                target=self._push_loop, daemon=True, name="push-loop"
            )
            self._push_thread.start()

        if self._enable_heartbeat:
            self._heartbeat_thread = threading.Thread(
                target=self._heartbeat_loop, daemon=True, name="heartbeat-loop"
            )
            self._heartbeat_thread.start()

        logger.info(
            "TTGO Bridge started. Transport: %s  Mode: %s",
            type(self._transport).__name__,
            MODE_TYPES[self._current_mode],
        )

    def wait(self):
        """Block until stop() is called."""
        self._stop_event.wait()

    def stop(self):
        self._running = False
        try:
            self._transport.stop()
        except Exception:
            pass
        self._stop_event.set()
        logger.info("TTGO Bridge stopped")

    # ── Serial event handler (called from read thread) ───────────────────────
    def _on_serial_event(self, obj: dict):
        event = obj.get("event", "")
        logger.debug("Serial event: %s", event)

        if event == "device_ready":
            logger.info("TTGO device ready — pushing current mode data")
            self._push_now(MODE_TYPES[self._current_mode])
            return

        if event == "mode_changed":
            new_idx = obj.get("mode", 0)
            if 0 <= new_idx < len(MODE_TYPES):
                old_mode = MODE_TYPES[self._current_mode]
                self._current_mode = new_idx
                new_mode = MODE_TYPES[new_idx]
                logger.info("Mode changed: %s → %s", old_mode, new_mode)

                # If TTGO enters image mode, capture/send exactly once.
                if new_mode == "image":
                    img_col = self._collectors.get("image")
                    if img_col is not None and hasattr(img_col, "invalidate_cache"):
                        img_col.invalidate_cache()
                    self._push_now("image")
                else:
                    self._push_now(new_mode)
            return

        if event == "ptt_start":
            logger.info("PTT start")
            try:
                self._voice.on_ptt_start()
            except Exception as e:
                logger.warning("voice.on_ptt_start failed: %s", e)
            return

        if event == "ptt_stop":
            logger.info("PTT stop")
            try:
                self._voice.on_ptt_stop()
            except Exception as e:
                logger.warning("voice.on_ptt_stop failed: %s", e)
            return

    def set_mode(self, mode_idx: int):
        """Remotely switch display mode via serial command."""
        if 0 <= mode_idx < len(MODE_TYPES):
            old_mode = MODE_TYPES[self._current_mode]
            self._current_mode = mode_idx
            new_mode = MODE_TYPES[mode_idx]
            logger.info("Remote mode switch: %s → %s", old_mode, new_mode)

            self._transport.send({"type": "set_mode", "mode": mode_idx})

            # Let firmware process set_mode / mode_changed
            time.sleep(self._mode_switch_delay)

            # For UX: push immediately when switching locally via set_mode.
            if new_mode == "image":
                img_col = self._collectors.get("image")
                if img_col is not None and hasattr(img_col, "invalidate_cache"):
                    img_col.invalidate_cache()
                self._push_now("image")
            else:
                self._push_now(new_mode)

            return

        logger.warning("set_mode: invalid mode_idx=%s", mode_idx)

    # ── Data push loop ───────────────────────────────────────────────────────
    def _push_loop(self):
        while self._running:
            now = time.monotonic()

            # Push ALL lightweight modes on their own intervals so the
            # firmware always has fresh data regardless of which mode the
            # TTGO is displaying. (Button events are unreliable over serial, so
            # the bridge can't trust _current_mode.)
            for mode in MODE_TYPES:
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

    def _heartbeat_loop(self):
        # Send immediately after start (so the first freshness window is covered).
        while self._running:
            try:
                now = time.time()
                # Small guard to avoid over-sending if clock jumps.
                if now - self._last_heartbeat >= self._heartbeat_interval:
                    self._transport.send({"type": "heartbeat", "ts": now})
                    self._last_heartbeat = now
            except Exception as e:
                logger.debug("Heartbeat send failed: %s", e)

            # Sleep a bit less than the interval so we don't drift too much.
            time.sleep(min(1.0, max(0.1, self._heartbeat_interval / 5.0)))

    def _send_ack(self, text: str):
        self._transport.send({"type": "ack", "text": text})


def _load_env_file(path: Path):
    if not path.exists():
        return

    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        os.environ.setdefault(k.strip(), v.strip())


# ── Entry point ───────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="TTGO T-Display Bridge")
    parser.add_argument("--debug", action="store_true", help="Enable debug logging")
    parser.add_argument(
        "--env-file",
        default=None,
        help="Optional env file to load before startup (dev/testing).",
    )
    parser.add_argument(
        "--transport",
        choices=["ws", "serial"],
        default="ws",
        help="Transport type: ws (WebSocket, default) or serial (USB fallback)",
    )
    args = parser.parse_args()

    level = logging.DEBUG if args.debug else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )

    # Load env before anything else.
    # Under systemd, secrets are already injected via EnvironmentFile=...,
    # so this is mainly for local/dev usage.
    if args.env_file:
        _load_env_file(Path(args.env_file).expanduser())
    else:
        _load_env_file(Path.home() / ".hermes" / ".env")

    bridge = TTGOBridge(transport_type=args.transport)

    def _shutdown(sig, frame):
        logger.info("Signal %s received — shutting down", sig)
        bridge.stop()

    signal.signal(signal.SIGINT, _shutdown)
    signal.signal(signal.SIGTERM, _shutdown)

    bridge.start()
    bridge.wait()
    logger.info("Bridge exited cleanly")


if __name__ == "__main__":
    main()
