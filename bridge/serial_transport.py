"""
serial_transport.py — Thread-safe serial read/write transport.

Reads newline-delimited JSON lines from /dev/ttyACM0 and calls the
registered event callback. Writes JSON dicts via an in-process queue.
Handles TTGO reboot/reconnect automatically.
"""

import json
import logging
import queue
import threading
import time
from typing import Callable, Optional

import serial

logger = logging.getLogger(__name__)

SERIAL_PORT    = "/dev/ttyACM0"
SERIAL_BAUD    = 2000000
RECONNECT_WAIT = 3.0   # seconds between reconnect attempts


class SerialTransport:
    def __init__(self, port: str = SERIAL_PORT, baud: int = SERIAL_BAUD,
                 on_event: Optional[Callable[[dict], None]] = None):
        self._port      = port
        self._baud      = baud
        self._on_event  = on_event
        self._queue: queue.Queue = queue.Queue(maxsize=64)
        self._ser: Optional[serial.Serial] = None
        self._running   = False
        self._connected = False
        self._read_thread:  Optional[threading.Thread] = None
        self._write_thread: Optional[threading.Thread] = None

    @property
    def connected(self) -> bool:
        return self._connected

    def start(self):
        self._running = True
        self._read_thread  = threading.Thread(target=self._read_loop,  daemon=True, name="serial-read")
        self._write_thread = threading.Thread(target=self._write_loop, daemon=True, name="serial-write")
        self._read_thread.start()
        self._write_thread.start()
        logger.info("SerialTransport started on %s @ %d", self._port, self._baud)

    def stop(self):
        self._running = False
        self._queue.put(None)   # unblock write loop
        if self._ser:
            try:
                self._ser.close()
            except Exception:
                pass
        logger.info("SerialTransport stopped")

    def send(self, data: dict):
        """Queue a dict to be sent as a JSON line."""
        try:
            self._queue.put_nowait(data)
        except queue.Full:
            logger.warning("Serial send queue full — dropping packet")

    # ── Internal threads ─────────────────────────────────────────────────────

    def _connect(self) -> bool:
        try:
            self._ser = serial.Serial(self._port, self._baud, timeout=2.0)
            # Allow ESP32 to finish booting if just connected
            time.sleep(1.5)
            self._connected = True
            logger.info("Serial connected to %s", self._port)
            return True
        except serial.SerialException as e:
            logger.warning("Serial connect failed: %s", e)
            self._connected = False
            return False

    def _read_loop(self):
        while self._running:
            if not self._connected or self._ser is None:
                if not self._connect():
                    time.sleep(RECONNECT_WAIT)
                    continue

            try:
                line = self._ser.readline()
                if not line:
                    continue
                text = line.decode("utf-8", errors="replace").strip()
                if not text:
                    continue
                try:
                    obj = json.loads(text)
                    if self._on_event and isinstance(obj, dict):
                        self._on_event(obj)
                except json.JSONDecodeError:
                    logger.debug("Serial bad JSON: %r", text)

            except serial.SerialException as e:
                logger.warning("Serial read error: %s — reconnecting", e)
                self._connected = False
                try:
                    self._ser.close()
                except Exception:
                    pass
                self._ser = None
                time.sleep(RECONNECT_WAIT)

    def _write_loop(self):
        while self._running:
            try:
                item = self._queue.get(timeout=1.0)
            except queue.Empty:
                continue

            if item is None:
                break   # stop signal

            if not self._connected or self._ser is None:
                continue   # drop writes while disconnected

            try:
                line = json.dumps(item, separators=(",", ":")) + "\n"
                self._ser.write(line.encode("utf-8"))
                self._ser.flush()
            except serial.SerialException as e:
                logger.warning("Serial write error: %s", e)
                self._connected = False
