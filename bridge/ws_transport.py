"""
ws_transport.py — WebSocket server transport (replaces serial_transport.py).

Runs an asyncio WebSocket server that waits for the TTGO to connect.
Accepts exactly one client at a time (the TTGO device).
Provides the same interface as SerialTransport:
  start()        — start the WS server background thread
  stop()         — shut down cleanly
  send(dict)     — queue a JSON message to send to TTGO
  connected      — True when TTGO client is connected

JSON framing: each WS text frame = one JSON object (no newline needed).
"""

import asyncio
import json
import logging
import queue
import threading
from typing import Callable, Optional

import websockets
from websockets.asyncio.server import ServerConnection

logger = logging.getLogger(__name__)

WS_HOST = "0.0.0.0"
WS_PORT = 8765
RECONNECT_WAIT = 3.0  # seconds to wait if no client after disconnect


class WsTransport:
    def __init__(
        self,
        host: str = WS_HOST,
        port: int = WS_PORT,
        on_event: Optional[Callable[[dict], None]] = None,
    ):
        self._host = host
        self._port = port
        self._on_event = on_event
        self._queue: queue.Queue = queue.Queue(maxsize=64)
        self._connected = False
        self._running = False
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._thread: Optional[threading.Thread] = None
        self._ws_client: Optional[ServerConnection] = None
        self._stop_event: Optional[asyncio.Event] = None

    @property
    def connected(self) -> bool:
        return self._connected

    def start(self):
        self._running = True
        self._thread = threading.Thread(
            target=self._run_loop, daemon=True, name="ws-server"
        )
        self._thread.start()
        logger.info("WsTransport started on %s:%d", self._host, self._port)

    def stop(self):
        self._running = False
        if self._loop and not self._loop.is_closed():
            self._loop.call_soon_threadsafe(
                lambda: self._stop_event.set() if self._stop_event else None
            )
        logger.info("WsTransport stopped")

    def send(self, data: dict):
        """Queue a dict to be sent as a JSON WS frame."""
        try:
            self._queue.put_nowait(data)
        except queue.Full:
            logger.warning("WS send queue full — dropping packet")

    # ── Internal ───────────────────────────────────────────────────────────────────

    def _run_loop(self):
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        self._stop_event = asyncio.Event()
        try:
            self._loop.run_until_complete(self._serve())
        finally:
            self._loop.close()

    async def _serve(self):
        async with websockets.serve(self._handle_client, self._host, self._port):
            logger.info("WebSocket server listening on ws://%s:%d", self._host, self._port)
            await self._stop_event.wait()

    async def _handle_client(self, ws: ServerConnection):
        """Handle one TTGO client connection."""
        remote = ws.remote_address
        logger.info("TTGO connected from %s", remote)
        self._ws_client = ws
        self._connected = True

        # Spawn sender task
        sender = asyncio.ensure_future(self._sender_loop(ws))

        try:
            async for message in ws:
                try:
                    obj = json.loads(message)
                    if self._on_event and isinstance(obj, dict):
                        self._on_event(obj)
                except json.JSONDecodeError:
                    logger.debug("WS bad JSON: %r", message)
        except websockets.exceptions.ConnectionClosed:
            pass
        finally:
            sender.cancel()
            self._connected = False
            self._ws_client = None
            logger.info("TTGO disconnected from %s", remote)

    async def _sender_loop(self, ws: ServerConnection):
        """Drain the send queue and forward messages to the WS client."""
        loop = asyncio.get_event_loop()
        while True:
            try:
                try:
                    item = await loop.run_in_executor(
                        None, lambda: self._queue.get(timeout=0.1)
                    )
                except queue.Empty:
                    continue

                if item is None:
                    break

                try:
                    frame = json.dumps(item, separators=(",", ":"))
                    await ws.send(frame)
                except websockets.exceptions.ConnectionClosed:
                    break
                except Exception as e:
                    logger.warning("WS send error: %s", e)

            except asyncio.CancelledError:
                break
