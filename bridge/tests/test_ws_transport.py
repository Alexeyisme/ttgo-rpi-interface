"""
Tests for WsTransport — WebSocket server transport.
"""

import asyncio
import json
import time
import pytest
import websockets

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from ws_transport import WsTransport

WS_TEST_PORT = 8766


@pytest.fixture
def transport():
    received = []
    t = WsTransport(port=WS_TEST_PORT, on_event=received.append)
    t.start()
    time.sleep(0.5)
    yield t, received
    t.stop()
    time.sleep(0.2)


def test_server_starts_and_accepts_client(transport):
    t, _ = transport
    async def _connect():
        async with websockets.connect(f"ws://127.0.0.1:{WS_TEST_PORT}"):
            await asyncio.sleep(0.1)
    asyncio.run(_connect())


def test_connected_flag_set_and_cleared(transport):
    t, _ = transport
    assert t.connected is False
    connected_during = []
    async def _connect():
        async with websockets.connect(f"ws://127.0.0.1:{WS_TEST_PORT}"):
            await asyncio.sleep(0.2)
            connected_during.append(t.connected)
    asyncio.run(_connect())
    time.sleep(0.2)
    assert connected_during == [True]
    assert t.connected is False


def test_server_receives_event_from_client(transport):
    t, received = transport
    async def _send():
        async with websockets.connect(f"ws://127.0.0.1:{WS_TEST_PORT}") as ws:
            await ws.send(json.dumps({"event": "ptt_start"}))
            await asyncio.sleep(0.2)
    asyncio.run(_send())
    time.sleep(0.1)
    assert any(m.get("event") == "ptt_start" for m in received)


def test_send_delivers_message_to_client(transport):
    t, _ = transport
    payload = {"type": "stats", "cpu": 42.0, "ram": 512}
    result_holder = []
    async def _recv():
        async with websockets.connect(f"ws://127.0.0.1:{WS_TEST_PORT}") as ws:
            await asyncio.sleep(0.15)
            t.send(payload)
            msg = await asyncio.wait_for(ws.recv(), timeout=3.0)
            result_holder.append(json.loads(msg))
    asyncio.run(_recv())
    assert result_holder, "No message received"
    assert result_holder[0]["type"] == "stats"
    assert result_holder[0]["cpu"] == 42.0


def test_send_queue_full_drops_gracefully(transport):
    t, _ = transport
    for i in range(70):
        t.send({"type": "stats", "i": i})


def test_server_handles_bad_json_from_client(transport):
    t, received = transport
    async def _send_garbage():
        async with websockets.connect(f"ws://127.0.0.1:{WS_TEST_PORT}") as ws:
            await ws.send("this is not json {{{")
            await asyncio.sleep(0.1)
            await ws.send(json.dumps({"event": "device_ready"}))
            await asyncio.sleep(0.1)
    asyncio.run(_send_garbage())
    time.sleep(0.1)
    assert any(m.get("event") == "device_ready" for m in received)


def test_reconnect_works(transport):
    t, received = transport
    async def _two_connections():
        async with websockets.connect(f"ws://127.0.0.1:{WS_TEST_PORT}") as ws:
            await ws.send(json.dumps({"event": "conn1"}))
            await asyncio.sleep(0.1)
        await asyncio.sleep(0.2)
        async with websockets.connect(f"ws://127.0.0.1:{WS_TEST_PORT}") as ws:
            await ws.send(json.dumps({"event": "conn2"}))
            await asyncio.sleep(0.1)
    asyncio.run(_two_connections())
    time.sleep(0.2)
    events = [m.get("event") for m in received]
    assert "conn1" in events
    assert "conn2" in events
